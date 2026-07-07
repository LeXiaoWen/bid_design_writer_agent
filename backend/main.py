from datetime import datetime
import os
from urllib.parse import quote, unquote

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from dotenv import load_dotenv

from .schemas import (
    ApiConfig,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthSetupRequest,
    AuthStatus,
    AuthUser,
    BehaviorReportEmail,
    BidWorkflow,
    BidWorkflowActionResponse,
    BidWorkflowConfirmRequest,
    BidWorkflowCreateResponse,
    BidWorkflowGenerateRequest,
    BidWorkflowStatus,
    ChangePasswordRequest,
    ChatStreamRequest,
    ConfirmRequest,
    ExtractRequest,
    GenerateRequest,
    ProviderModelsResponse,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    ProjectStage,
    TextResponse,
    UploadResponse,
    WorkbenchConversationCreate,
    WorkbenchConversationUpdate,
    WorkbenchProjectCreate,
    WorkbenchProjectUpdate,
)
from .services.artifacts import build_output_files, list_artifacts, make_zip
from .services.auth import change_password, login_user, logout_token, setup_user, user_from_token
from .services.behavior_report_email import send_behavior_report_email
from .services.config import API_PRESETS
from .services.document_parser import parse_document
from .services.llm import run_agent
from .services.project_store import store
from .services.provider_models import list_provider_models as fetch_provider_models
from .services.skill_loader import (
    build_confirmation_instructions,
    build_stage1_instructions,
    build_stage2_instructions,
    resolve_skill_dir,
)
from .services.workbench_llm import cancel_run, stream_chat
from .services.workbench_store import db_path, workbench_store

load_dotenv()


def get_cors_origins() -> list[str]:
    raw = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,app://frontend,null")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


LOCAL_FRONTEND_ORIGIN_REGEX = r"^(https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?|app://frontend|null)$"


app = FastAPI(title="AI Workbench Desktop Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_origin_regex=os.getenv("FRONTEND_ORIGIN_REGEX", LOCAL_FRONTEND_ORIGIN_REGEX),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)

PUBLIC_API_V1_PATHS = {
    "/api/v1/auth/status",
    "/api/v1/auth/setup",
    "/api/v1/auth/login",
}


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def app_auth_secret_is_valid(request: Request) -> bool:
    expected = os.getenv("APP_AUTH_SECRET", "").strip()
    if not expected:
        return True
    return request.headers.get("x-app-auth-secret", "") == expected


@app.middleware("http")
async def require_local_auth(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    if not path.startswith("/api/v1/") or path in PUBLIC_API_V1_PATHS:
        return await call_next(request)

    if not app_auth_secret_is_valid(request):
        return JSONResponse(status_code=403, content={"detail": "本机访问密钥无效。"})

    user = user_from_token(bearer_token(request))
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "请先登录。"})
    request.state.user = user
    return await call_next(request)


def current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


def get_project_or_404(project_id: str):
    try:
        return store.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


def truncate_text(text: str, max_chars: int = 120_000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[文本过长，已截断。请优先基于已有内容提取，并提示用户可补充缺失页。]"


def is_confirmation(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized.startswith(("不确认", "未确认", "不能确认")):
        return False
    exact_matches = {"确认", "确认无误", "无误", "正确", "没问题", "可以", "ok", "yes", "y"}
    return normalized in exact_matches or normalized.startswith(("确认无误", "信息无误"))


def api_config_from_profile(provider_profile_id: str) -> ApiConfig:
    profile = workbench_store.get_provider_profile(provider_profile_id)
    api_key = workbench_store.resolve_api_key(provider_profile_id)
    if not api_key:
        raise ValueError("请先配置 API key。")
    return ApiConfig(provider=profile.provider, base_url=profile.base_url, api_key=api_key, model=profile.model)


def template_display_name(template_choice: str) -> str:
    if template_choice == "auto":
        return "按招标文件自动判断目录结构"
    return "12 章设计标模板" if template_choice == "12-chapter" else "5 章全过程咨询标模板"


def workflow_is_cancelled(workflow_id: str) -> bool:
    return workbench_store.get_bid_workflow(workflow_id).status == BidWorkflowStatus.CANCELLED


def run_bid_extraction_task(workflow_id: str) -> None:
    workflow = workbench_store.get_bid_workflow(workflow_id)
    try:
        if workflow.status == BidWorkflowStatus.CANCELLED:
            return
        api_config = api_config_from_profile(workflow.provider_profile_id or "")
        prompt = f"""
请执行阶段一：从以下招标文件文本中提取四类关键信息，并按 Skill 要求输出。

文件名：{workflow.file_name}
提取时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}

招标文件文本：
{truncate_text(workflow.file_text)}
"""
        result = run_agent(api_config, build_stage1_instructions(), prompt)
        if workflow_is_cancelled(workflow_id):
            return
        saved = workbench_store.save_bid_extraction(workflow_id, result)
        workbench_store.add_message(
            saved.conversation_id,
            "assistant",
            f"{result}\n\n请确认以上信息是否准确。确认后可进入阶段二生成设计方案。",
        )
    except Exception as exc:
        failed = workbench_store.update_bid_workflow_status(workflow_id, BidWorkflowStatus.FAILED, error=str(exc))
        workbench_store.add_message(failed.conversation_id, "assistant", f"阶段一提取失败：{exc}", status="error", error=str(exc))


def run_bid_generation_task(workflow_id: str) -> None:
    workflow = workbench_store.get_bid_workflow(workflow_id)
    try:
        if workflow.status == BidWorkflowStatus.CANCELLED:
            return
        if not workflow.extracted_markdown:
            raise ValueError("请先完成阶段一信息提取。")
        if workflow.template_choice not in {"auto", "12-chapter", "5-chapter"}:
            raise ValueError("模板选择无效，请使用 auto、12-chapter 或 5-chapter。")

        api_config = api_config_from_profile(workflow.provider_profile_id or "")
        prompt = f"""
用户已确认阶段一提取结果，目录结构选择方式：{template_display_name(workflow.template_choice)}

用户确认/补充信息：
{workflow.confirmation_text or "确认无补充。"}

阶段一提取结果：
{workflow.extracted_markdown}

请执行阶段二：生成完整设计方案、绘图提示词 + 专业图纸需求清单、标书制作规范汇总。
"""
        result = run_agent(api_config, build_stage2_instructions(workflow.template_choice), prompt)
        if workflow_is_cancelled(workflow_id):
            return
        files = build_output_files(workflow.extracted_markdown, result)
        workbench_store.save_bid_artifacts(workflow_id, files)
        completed = workbench_store.get_bid_workflow(workflow_id)
        send_behavior_report_email(completed.id)
        workbench_store.add_message(completed.conversation_id, "assistant", f"{result}\n\n生成完成，可下载 Markdown 文件或 ZIP 包。")
    except Exception as exc:
        failed = workbench_store.update_bid_workflow_status(workflow_id, BidWorkflowStatus.FAILED, error=str(exc))
        workbench_store.add_message(failed.conversation_id, "assistant", f"阶段二生成失败：{exc}", status="error", error=str(exc))


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "ai-workbench-desktop",
        "legacy_app": "bid-design-writer-desktop",
        "version": "0.1.0",
        "skill_dir": str(resolve_skill_dir()),
        "database": str(db_path()),
        "presets": API_PRESETS,
    }


@app.get("/api/v1/auth/status", response_model=AuthStatus)
def get_auth_status(request: Request):
    user = user_from_token(bearer_token(request))
    first_user = workbench_store.get_first_user()
    return AuthStatus(
        setup_required=first_user is None,
        authenticated=user is not None,
        username=user.username if user else None,
    )


@app.post("/api/v1/auth/setup", response_model=AuthLoginResponse)
def setup_auth(request: AuthSetupRequest):
    if workbench_store.has_user():
        raise HTTPException(status_code=400, detail="本机账号已存在，请直接登录。")
    try:
        setup_user(request.username, request.password)
        return login_user(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/auth/login", response_model=AuthLoginResponse)
def login_auth(request: AuthLoginRequest):
    try:
        return login_user(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/v1/auth/logout")
def logout_auth(request: Request):
    logout_token(bearer_token(request))
    return {"ok": True}


@app.get("/api/v1/me", response_model=AuthUser)
def get_me(request: Request):
    return current_user(request)


@app.post("/api/v1/auth/change-password")
def change_auth_password(request: Request, payload: ChangePasswordRequest):
    try:
        change_password(current_user(request), payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/v1/projects")
def list_workbench_projects():
    return workbench_store.list_projects()


@app.post("/api/v1/projects")
def create_workbench_project(request: WorkbenchProjectCreate):
    return workbench_store.create_project(request)


@app.get("/api/v1/projects/{project_id}")
def get_workbench_project(project_id: str):
    try:
        return workbench_store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.patch("/api/v1/projects/{project_id}")
def update_workbench_project(project_id: str, request: WorkbenchProjectUpdate):
    try:
        return workbench_store.update_project(project_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.delete("/api/v1/projects/{project_id}")
def delete_workbench_project(project_id: str):
    try:
        workbench_store.delete_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations")
def list_workbench_conversations(project_id: str | None = Query(default=None)):
    return workbench_store.list_conversations(project_id)


@app.post("/api/v1/conversations")
def create_workbench_conversation(request: WorkbenchConversationCreate):
    try:
        return workbench_store.create_conversation(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.get("/api/v1/conversations/{conversation_id}")
def get_workbench_conversation(conversation_id: str):
    try:
        return workbench_store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.patch("/api/v1/conversations/{conversation_id}")
def update_workbench_conversation(conversation_id: str, request: WorkbenchConversationUpdate):
    try:
        return workbench_store.update_conversation(conversation_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.delete("/api/v1/conversations/{conversation_id}")
def delete_workbench_conversation(conversation_id: str):
    try:
        workbench_store.delete_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations/{conversation_id}/messages")
def list_workbench_messages(conversation_id: str):
    try:
        workbench_store.get_conversation(conversation_id)
        return workbench_store.list_messages(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.get("/api/v1/provider-profiles")
def list_provider_profiles():
    return workbench_store.list_provider_profiles()


@app.post("/api/v1/provider-profiles")
def create_provider_profile(request: ProviderProfileCreate):
    return workbench_store.create_provider_profile(request)


@app.get("/api/v1/provider-profiles/{profile_id}/models", response_model=ProviderModelsResponse)
async def list_provider_models(profile_id: str):
    try:
        models = await fetch_provider_models(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型列表拉取失败：{exc}") from exc
    return ProviderModelsResponse(models=models)


@app.patch("/api/v1/provider-profiles/{profile_id}")
def update_provider_profile(profile_id: str, request: ProviderProfileUpdate):
    try:
        return workbench_store.update_provider_profile(profile_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc


@app.delete("/api/v1/provider-profiles/{profile_id}")
def delete_provider_profile(profile_id: str):
    try:
        workbench_store.delete_provider_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/search")
def search_workbench(q: str = Query(default="")):
    return workbench_store.search(q)


@app.post("/api/v1/chat/stream")
async def stream_workbench_chat(request: ChatStreamRequest):
    return StreamingResponse(stream_chat(request), media_type="text/event-stream")


@app.post("/api/v1/chat/{run_id}/cancel")
def cancel_workbench_chat(run_id: str):
    return {"ok": cancel_run(run_id)}


@app.post("/api/v1/bid-workflows", response_model=BidWorkflowCreateResponse)
async def create_bid_workflow(
    conversation_id: str = Form(...),
    provider_profile_id: str = Form(...),
    file: UploadFile = File(...),
):
    try:
        workbench_store.get_conversation(conversation_id)
        api_config_from_profile(provider_profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话或模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()
    file_name = file.filename or "uploaded"
    try:
        file_text = parse_document(file_name, content)
        workflow = workbench_store.create_bid_workflow(conversation_id, file_name, file_text, provider_profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话或模型配置不存在。") from exc

    workbench_store.add_message(conversation_id, "user", f"已上传招标文件：{file_name}")
    workbench_store.add_message(conversation_id, "assistant", "文件已解析。可以开始阶段一信息提取。")
    return BidWorkflowCreateResponse(**workflow.model_dump(), char_count=len(file_text), message="文件解析完成。")


@app.get("/api/v1/bid-workflows", response_model=list[BidWorkflow])
def list_bid_workflows(conversation_id: str | None = Query(default=None)):
    return workbench_store.list_bid_workflows(conversation_id)


@app.get("/api/v1/bid-workflows/{workflow_id}")
def get_bid_workflow(workflow_id: str):
    try:
        return workbench_store.get_bid_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@app.post("/api/v1/bid-workflows/{workflow_id}/extract", response_model=BidWorkflowActionResponse)
def extract_bid_workflow(workflow_id: str, background_tasks: BackgroundTasks):
    try:
        workflow = workbench_store.get_bid_workflow(workflow_id)
        api_config_from_profile(workflow.provider_profile_id or "")
        if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
            raise ValueError("当前工作流正在执行中。")
        if workflow.status == BidWorkflowStatus.COMPLETED:
            raise ValueError("当前工作流已完成。")
        workflow = workbench_store.update_bid_workflow_status(workflow_id, BidWorkflowStatus.EXTRACTING)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流或模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(workflow.conversation_id, "assistant", "正在执行阶段一信息提取。")
    background_tasks.add_task(run_bid_extraction_task, workflow_id)
    return BidWorkflowActionResponse(workflow=workflow, message="阶段一信息提取已开始。")


@app.post("/api/v1/bid-workflows/{workflow_id}/confirm", response_model=BidWorkflowActionResponse)
def confirm_bid_workflow(workflow_id: str, request: BidWorkflowConfirmRequest):
    try:
        workflow = workbench_store.get_bid_workflow(workflow_id)
        if not workflow.extracted_markdown:
            raise ValueError("请先完成阶段一信息提取。")
        if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
            raise ValueError("当前工作流正在执行中。")
        workflow = workbench_store.save_bid_confirmation(workflow_id, request.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(workflow.conversation_id, "user", request.text)
    return BidWorkflowActionResponse(workflow=workflow, message="阶段一信息已确认。")


@app.post("/api/v1/bid-workflows/{workflow_id}/generate", response_model=BidWorkflowActionResponse)
def generate_bid_workflow(workflow_id: str, request: BidWorkflowGenerateRequest, background_tasks: BackgroundTasks):
    try:
        workflow = workbench_store.get_bid_workflow(workflow_id)
        api_config_from_profile(workflow.provider_profile_id or "")
        if not workflow.extracted_markdown:
            raise ValueError("请先完成阶段一信息提取。")
        if not workflow.confirmation_text:
            raise ValueError("请先确认阶段一信息。")
        if request.template_choice not in {"auto", "12-chapter", "5-chapter"}:
            raise ValueError("模板选择无效，请使用 auto、12-chapter 或 5-chapter。")
        if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
            raise ValueError("当前工作流正在执行中。")
        confirmation_text = workflow.confirmation_text
        if request.extra_context:
            confirmation_text = f"{confirmation_text}\n\n补充信息：{request.extra_context}"
        workbench_store.save_bid_confirmation(workflow_id, confirmation_text)
        workbench_store.save_bid_template_choice(workflow_id, request.template_choice)
        workflow = workbench_store.update_bid_workflow_status(workflow_id, BidWorkflowStatus.GENERATING)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流或模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(workflow.conversation_id, "assistant", f"正在执行阶段二设计方案生成，模板：{template_display_name(request.template_choice)}。")
    background_tasks.add_task(run_bid_generation_task, workflow_id)
    return BidWorkflowActionResponse(workflow=workflow, message="阶段二设计方案生成已开始。")


@app.post("/api/v1/bid-workflows/{workflow_id}/cancel", response_model=BidWorkflowActionResponse)
def cancel_bid_workflow(workflow_id: str):
    try:
        workflow = workbench_store.get_bid_workflow(workflow_id)
        if workflow.status == BidWorkflowStatus.COMPLETED:
            raise ValueError("当前工作流已完成，不能取消。")
        if workflow.status == BidWorkflowStatus.CANCELLED:
            return BidWorkflowActionResponse(workflow=workflow, message="标书工作流已取消。")
        workflow = workbench_store.update_bid_workflow_status(workflow_id, BidWorkflowStatus.CANCELLED)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(workflow.conversation_id, "assistant", "当前标书流程已取消。")
    return BidWorkflowActionResponse(workflow=workflow, message="标书工作流已取消。")


@app.get("/api/v1/bid-workflows/{workflow_id}/report-email-status", response_model=list[BehaviorReportEmail])
def get_bid_workflow_report_email_status(workflow_id: str):
    try:
        return workbench_store.list_behavior_report_emails(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@app.post("/api/v1/bid-workflows/{workflow_id}/report-email/retry", response_model=list[BehaviorReportEmail])
def retry_bid_workflow_report_email(workflow_id: str):
    try:
        workbench_store.get_bid_workflow(workflow_id)
        return send_behavior_report_email(workflow_id, allow_retry=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@app.get("/api/v1/bid-workflows/{workflow_id}/artifacts")
def list_bid_workflow_artifacts(workflow_id: str):
    try:
        return workbench_store.list_bid_artifacts(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@app.get("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}")
def get_bid_workflow_artifact(workflow_id: str, name: str):
    decoded = unquote(name)
    try:
        content = workbench_store.get_bid_artifact_content(workflow_id, decoded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果文件不存在。") from exc
    return Response(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(decoded)}"},
    )


@app.get("/api/v1/bid-workflows/{workflow_id}/export.zip")
def export_bid_workflow_zip(workflow_id: str):
    try:
        files = workbench_store.get_bid_artifact_files(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
    if not files:
        raise HTTPException(status_code=404, detail="暂无可导出的成果文件。")
    return Response(
        make_zip(files),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''bid-workflow-artifacts.zip"},
    )


@app.post("/api/projects")
def create_project():
    project = store.create()
    return store.to_response(project)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return store.to_response(get_project_or_404(project_id))


@app.post("/api/projects/{project_id}/upload", response_model=UploadResponse)
async def upload_file(project_id: str, file: UploadFile = File(...)):
    project = get_project_or_404(project_id)
    content = await file.read()
    try:
        file_text = parse_document(file.filename or "uploaded", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project.file_name = file.filename
    project.file_text = file_text
    project.extracted_markdown = ""
    project.template_choice = ""
    project.artifacts = {}
    project.stage = ProjectStage.UPLOADED
    project.add_message("user", f"已上传招标文件：{file.filename}")
    project.add_message("assistant", "文件已解析。点击“开始提取”执行阶段一信息提取。")
    return UploadResponse(
        project_id=project.project_id,
        stage=project.stage,
        file_name=file.filename or "uploaded",
        char_count=len(file_text),
        message="文件解析完成。",
    )


@app.post("/api/projects/{project_id}/extract", response_model=TextResponse)
def extract_project(project_id: str, request: ExtractRequest):
    project = get_project_or_404(project_id)
    if not project.file_text:
        raise HTTPException(status_code=400, detail="请先上传招标文件。")

    prompt = f"""
请执行阶段一：从以下招标文件文本中提取四类关键信息，并按 Skill 要求输出。

文件名：{project.file_name}
提取时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}

招标文件文本：
{truncate_text(project.file_text)}
"""
    project.stage = ProjectStage.CONFIRMING
    try:
        result = run_agent(request.api_config, build_stage1_instructions(), prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"阶段一提取失败：{exc}") from exc

    project.extracted_markdown = result
    project.add_message("assistant", f"{result}\n\n请确认以上信息是否准确。你可以直接回复“确认”，也可以指出需要修正的内容。")
    return TextResponse(project_id=project.project_id, stage=project.stage, message=result, extracted_markdown=result)


@app.post("/api/projects/{project_id}/confirm", response_model=TextResponse)
def confirm_project(project_id: str, request: ConfirmRequest):
    project = get_project_or_404(project_id)
    if not project.extracted_markdown:
        raise HTTPException(status_code=400, detail="请先完成阶段一信息提取。")

    project.add_message("user", request.text)
    if is_confirmation(request.text):
        project.stage = ProjectStage.TEMPLATE_SELECT
        message = "已确认阶段一信息。请选择标书模板：A. 12 章设计标模板，或 B. 5 章全过程咨询标模板。"
        project.add_message("assistant", message)
        return TextResponse(
            project_id=project.project_id,
            stage=project.stage,
            message=message,
            extracted_markdown=project.extracted_markdown,
        )

    if request.api_config is None:
        raise HTTPException(status_code=400, detail="修正阶段一结果需要提供 API 配置。")

    prompt = f"""
这是当前提取结果：

{project.extracted_markdown}

用户修正/补充：
{request.text}

请输出更新后的完整阶段一提取结果。
"""
    try:
        result = run_agent(request.api_config, build_confirmation_instructions(), prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"阶段一结果更新失败：{exc}") from exc

    project.extracted_markdown = result
    project.stage = ProjectStage.CONFIRMING
    project.add_message("assistant", f"{result}\n\n请继续确认。确认无误后回复“确认”。")
    return TextResponse(project_id=project.project_id, stage=project.stage, message=result, extracted_markdown=result)


@app.post("/api/projects/{project_id}/generate", response_model=TextResponse)
def generate_project(project_id: str, request: GenerateRequest):
    project = get_project_or_404(project_id)
    if not project.extracted_markdown:
        raise HTTPException(status_code=400, detail="请先完成阶段一信息提取。")
    if project.stage != ProjectStage.TEMPLATE_SELECT:
        raise HTTPException(status_code=400, detail="请先确认阶段一信息后再生成方案。")
    if request.template_choice not in {"12-chapter", "5-chapter"}:
        raise HTTPException(status_code=400, detail="模板选择无效，请使用 12-chapter 或 5-chapter。")

    project.stage = ProjectStage.GENERATING
    project.template_choice = request.template_choice
    template_name = "12 章设计标模板" if request.template_choice == "12-chapter" else "5 章全过程咨询标模板"
    prompt = f"""
用户已确认阶段一提取结果，并选择：{template_name}

阶段一提取结果：
{project.extracted_markdown}

请执行阶段二：生成完整设计方案、绘图提示词 + 专业图纸需求清单、标书制作规范汇总。
"""
    try:
        result = run_agent(request.api_config, build_stage2_instructions(request.template_choice), prompt)
    except Exception as exc:
        project.stage = ProjectStage.TEMPLATE_SELECT
        raise HTTPException(status_code=502, detail=f"阶段二生成失败：{exc}") from exc

    project.artifacts = build_output_files(project.extracted_markdown, result)
    project.stage = ProjectStage.DONE
    project.add_message("assistant", f"{result}\n\n生成完成。左侧已提供 Markdown 和 ZIP 下载。")
    return TextResponse(project_id=project.project_id, stage=project.stage, message=result, artifacts=project.artifacts)


@app.get("/api/projects/{project_id}/artifacts")
def artifacts(project_id: str):
    project = get_project_or_404(project_id)
    return list_artifacts(project.artifacts)


@app.get("/api/projects/{project_id}/artifacts/{name}")
def artifact(project_id: str, name: str):
    project = get_project_or_404(project_id)
    decoded = unquote(name)
    if decoded not in project.artifacts:
        raise HTTPException(status_code=404, detail="成果文件不存在。")
    return Response(
        project.artifacts[decoded],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(decoded)}"},
    )


@app.get("/api/projects/{project_id}/export.zip")
def export_zip(project_id: str):
    project = get_project_or_404(project_id)
    if not project.artifacts:
        raise HTTPException(status_code=404, detail="暂无可导出的成果文件。")
    return Response(
        make_zip(project.artifacts),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''bid-design-writer-artifacts.zip"},
    )
