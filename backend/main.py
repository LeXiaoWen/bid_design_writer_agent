from datetime import datetime
import os
import re
from urllib.parse import quote, unquote

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from dotenv import load_dotenv

from .schemas import (
    ApiConfig,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthRegisterRequest,
    AuthStatus,
    AuthUser,
    BidWorkflow,
    BidWorkflowActionResponse,
    BidWorkflowConfirmRequest,
    BidWorkflowCreateResponse,
    BidWorkflowGenerateRequest,
    BidWorkflowPublic,
    BidWorkflowStatus,
    ChangePasswordRequest,
    ChatStreamRequest,
    ProviderModelsResponse,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    WorkbenchConversationCreate,
    WorkbenchConversationUpdate,
    WorkbenchProjectCreate,
    WorkbenchProjectUpdate,
    WebSearchConfig,
    WebSearchConfigUpdate,
)
from .services.artifacts import build_output_files, make_zip
from .services.auth import AuthRateLimitError, change_password, login_user, logout_token, register_user, user_from_token
from .services.behavior_report import save_behavior_report
from .services.config import API_PRESETS
from .services.document_parser import parse_document
from .services.llm import run_agent
from .services.provider_models import list_provider_models as fetch_provider_models
from .services.skill_loader import (
    build_stage1_instructions,
    build_stage2_instructions,
    skill_source_label,
)
from .services.workbench_llm import cancel_run, stream_chat
from .services.workbench_store import db_path, workbench_store

load_dotenv()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


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
    "/api/v1/auth/register",
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


def auth_error_response(request: Request, status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    origin = request.headers.get("origin")
    origin_is_allowed = origin in get_cors_origins()
    origin_regex = os.getenv("FRONTEND_ORIGIN_REGEX", LOCAL_FRONTEND_ORIGIN_REGEX)
    if origin and (origin_is_allowed or re.match(origin_regex, origin)):
        response.headers["access-control-allow-origin"] = origin
        response.headers["access-control-allow-credentials"] = "true"
        response.headers["access-control-allow-private-network"] = "true"
        response.headers["vary"] = "Origin"
    return response


@app.middleware("http")
async def require_local_auth(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    protected_path = path.startswith("/api/v1/")
    if not protected_path:
        return await call_next(request)

    if not app_auth_secret_is_valid(request):
        return auth_error_response(request, 403, "本机访问密钥无效。")

    if path in PUBLIC_API_V1_PATHS:
        return await call_next(request)

    user = user_from_token(bearer_token(request))
    if user is None:
        return auth_error_response(request, 401, "请先登录。")
    request.state.user = user
    return await call_next(request)


def current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


async def read_upload_with_limit(file: UploadFile, max_bytes: int | None = None) -> bytes:
    limit = max_bytes or MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError(f"上传文件不能超过 {limit // (1024 * 1024)}MB。")
        chunks.append(chunk)
    return b"".join(chunks)


def truncate_text(text: str, max_chars: int = 120_000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[文本过长，已截断。请优先基于已有内容提取，并提示用户可补充缺失页。]"


def api_config_from_profile(user_id: str, provider_profile_id: str) -> ApiConfig:
    profile = workbench_store.get_provider_profile(user_id, provider_profile_id)
    api_key = workbench_store.resolve_api_key(user_id, provider_profile_id)
    if not api_key:
        raise ValueError("请先配置 API key。")
    return ApiConfig(provider=profile.provider, base_url=profile.base_url, api_key=api_key, model=profile.model)


def public_bid_workflow(workflow: BidWorkflow) -> BidWorkflowPublic:
    return BidWorkflowPublic.model_validate(workflow.model_dump(exclude={"file_text"}))


def workflow_is_cancelled(user_id: str, workflow_id: str) -> bool:
    return workbench_store.get_bid_workflow(user_id, workflow_id).status == BidWorkflowStatus.CANCELLED


def run_bid_extraction_task(user_id: str, workflow_id: str) -> None:
    workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
    try:
        if workflow.status == BidWorkflowStatus.CANCELLED:
            return
        api_config = api_config_from_profile(user_id, workflow.provider_profile_id or "")
        prompt = f"""
请执行阶段一：从以下招标文件文本中提取四类关键信息，并按 Skill 要求输出。

文件名：{workflow.file_name}
提取时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}

招标文件文本：
{truncate_text(workflow.file_text)}
"""
        result = run_agent(api_config, build_stage1_instructions(), prompt)
        if workflow_is_cancelled(user_id, workflow_id):
            return
        saved = workbench_store.save_bid_extraction(user_id, workflow_id, result)
        workbench_store.add_message(
            user_id,
            saved.conversation_id,
            "assistant",
            f"{result}\n\n请确认以上信息是否准确。确认后可进入阶段二生成设计方案。",
        )
    except Exception as exc:
        failed = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.FAILED, error=str(exc))
        workbench_store.add_message(user_id, failed.conversation_id, "assistant", f"阶段一提取失败：{exc}", status="error", error=str(exc))


def run_bid_generation_task(user_id: str, workflow_id: str) -> None:
    workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
    try:
        if workflow.status == BidWorkflowStatus.CANCELLED:
            return
        if not workflow.extracted_markdown:
            raise ValueError("请先完成阶段一信息提取。")
        api_config = api_config_from_profile(user_id, workflow.provider_profile_id or "")
        prompt = f"""
用户已确认阶段一提取结果。请仅按当前招标范围、评分、成果和格式要求动态编排目录，不使用预设模板。

用户确认/补充信息：
{workflow.confirmation_text or "确认无补充。"}

阶段一提取结果：
{workflow.extracted_markdown}

请执行阶段二：生成当前建筑设计范围内的完整方案。图文需求、制作规范汇总和其他附表仅在当前招标文件或已确认资料实际触发时输出。
"""
        result = run_agent(api_config, build_stage2_instructions(), prompt)
        if workflow_is_cancelled(user_id, workflow_id):
            return
        files = build_output_files(workflow.extracted_markdown, result)
        workbench_store.save_bid_artifacts(user_id, workflow_id, files)
        completed = workbench_store.get_bid_workflow(user_id, workflow_id)
        try:
            save_behavior_report(user_id, completed.id)
        except Exception as report_exc:
            print(f"[behavior-report] failed to save report for {completed.id}: {report_exc}")
        workbench_store.add_message(user_id, completed.conversation_id, "assistant", f"{result}\n\n生成完成，可下载 Markdown 文件或 ZIP 包。")
    except Exception as exc:
        failed = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.FAILED, error=str(exc))
        workbench_store.add_message(user_id, failed.conversation_id, "assistant", f"阶段二生成失败：{exc}", status="error", error=str(exc))


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "ai-workbench-desktop",
        "version": "0.1.0",
        "skill_dir": skill_source_label(),
        "database": str(db_path()),
        "presets": API_PRESETS,
    }


@app.get("/api/v1/auth/status", response_model=AuthStatus)
def get_auth_status(request: Request):
    user = user_from_token(bearer_token(request))
    return AuthStatus(
        authenticated=user is not None,
        username=user.username if user else None,
    )


@app.post("/api/v1/auth/register", response_model=AuthLoginResponse)
def register_auth(request: AuthRegisterRequest):
    try:
        register_user(request.username, request.password)
        return login_user(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/auth/login", response_model=AuthLoginResponse)
def login_auth(request: AuthLoginRequest):
    try:
        return login_user(request.username, request.password)
    except AuthRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
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
def list_workbench_projects(request: Request):
    return workbench_store.list_projects(current_user(request).id)


@app.post("/api/v1/projects")
def create_workbench_project(request: Request, payload: WorkbenchProjectCreate):
    return workbench_store.create_project(current_user(request).id, payload)


@app.get("/api/v1/projects/{project_id}")
def get_workbench_project(project_id: str, request: Request):
    try:
        return workbench_store.get_project(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.patch("/api/v1/projects/{project_id}")
def update_workbench_project(project_id: str, request: Request, payload: WorkbenchProjectUpdate):
    try:
        return workbench_store.update_project(current_user(request).id, project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.delete("/api/v1/projects/{project_id}")
def delete_workbench_project(project_id: str, request: Request):
    try:
        workbench_store.delete_project(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations")
def list_workbench_conversations(request: Request, project_id: str | None = Query(default=None)):
    return workbench_store.list_conversations(current_user(request).id, project_id)


@app.post("/api/v1/conversations")
def create_workbench_conversation(request: Request, payload: WorkbenchConversationCreate):
    try:
        return workbench_store.create_conversation(current_user(request).id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@app.get("/api/v1/conversations/{conversation_id}")
def get_workbench_conversation(conversation_id: str, request: Request):
    try:
        return workbench_store.get_conversation(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.patch("/api/v1/conversations/{conversation_id}")
def update_workbench_conversation(conversation_id: str, request: Request, payload: WorkbenchConversationUpdate):
    try:
        return workbench_store.update_conversation(current_user(request).id, conversation_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.delete("/api/v1/conversations/{conversation_id}")
def delete_workbench_conversation(conversation_id: str, request: Request):
    try:
        workbench_store.delete_conversation(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/conversations/{conversation_id}/messages")
def list_workbench_messages(conversation_id: str, request: Request):
    try:
        return workbench_store.list_messages(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@app.get("/api/v1/provider-profiles")
def list_provider_profiles(request: Request):
    return workbench_store.list_provider_profiles(current_user(request).id)


@app.post("/api/v1/provider-profiles")
def create_provider_profile(request: Request, payload: ProviderProfileCreate):
    return workbench_store.create_provider_profile(current_user(request).id, payload)


@app.get("/api/v1/provider-profiles/{profile_id}/models", response_model=ProviderModelsResponse)
async def list_provider_models(profile_id: str, request: Request):
    try:
        models = await fetch_provider_models(current_user(request).id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型列表拉取失败：{exc}") from exc
    return ProviderModelsResponse(models=models)


@app.patch("/api/v1/provider-profiles/{profile_id}")
def update_provider_profile(profile_id: str, request: Request, payload: ProviderProfileUpdate):
    try:
        return workbench_store.update_provider_profile(current_user(request).id, profile_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc


@app.delete("/api/v1/provider-profiles/{profile_id}")
def delete_provider_profile(profile_id: str, request: Request):
    try:
        workbench_store.delete_provider_profile(current_user(request).id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    return {"ok": True}


@app.get("/api/v1/search")
def search_workbench(request: Request, q: str = Query(default="")):
    return workbench_store.search(current_user(request).id, q)


@app.get("/api/v1/web-search-config", response_model=WebSearchConfig)
def get_web_search_config(request: Request):
    return workbench_store.get_web_search_config(current_user(request).id)


@app.patch("/api/v1/web-search-config", response_model=WebSearchConfig)
def update_web_search_config(request: Request, payload: WebSearchConfigUpdate):
    return workbench_store.update_web_search_config(current_user(request).id, payload)


@app.post("/api/v1/chat/stream")
async def stream_workbench_chat(request: Request, payload: ChatStreamRequest):
    return StreamingResponse(stream_chat(current_user(request).id, payload), media_type="text/event-stream")


@app.post("/api/v1/chat/{run_id}/cancel")
def cancel_workbench_chat(run_id: str, request: Request):
    return {"ok": cancel_run(current_user(request).id, run_id)}


@app.post("/api/v1/bid-workflows", response_model=BidWorkflowCreateResponse)
async def create_bid_workflow(
    request: Request,
    conversation_id: str = Form(...),
    provider_profile_id: str = Form(...),
    file: UploadFile = File(...),
):
    user_id = current_user(request).id
    try:
        workbench_store.get_conversation(user_id, conversation_id)
        api_config_from_profile(user_id, provider_profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话或模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_name = file.filename or "uploaded"
    try:
        content = await read_upload_with_limit(file)
        file_text = parse_document(file_name, content)
        workflow = workbench_store.create_bid_workflow(user_id, conversation_id, file_name, file_text, provider_profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话或模型配置不存在。") from exc

    workbench_store.add_message(user_id, conversation_id, "user", f"已上传招标文件：{file_name}")
    workbench_store.add_message(user_id, conversation_id, "assistant", "文件已解析。可以开始阶段一信息提取。")
    return BidWorkflowCreateResponse(**workflow.model_dump(exclude={"file_text"}), char_count=len(file_text), message="文件解析完成。")


@app.get("/api/v1/bid-workflows", response_model=list[BidWorkflowPublic])
def list_bid_workflows(request: Request, conversation_id: str | None = Query(default=None)):
    return [public_bid_workflow(workflow) for workflow in workbench_store.list_bid_workflows(current_user(request).id, conversation_id)]


@app.get("/api/v1/bid-workflows/{workflow_id}", response_model=BidWorkflowPublic)
def get_bid_workflow(workflow_id: str, request: Request):
    try:
        return public_bid_workflow(workbench_store.get_bid_workflow(current_user(request).id, workflow_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@app.post("/api/v1/bid-workflows/{workflow_id}/extract", response_model=BidWorkflowActionResponse)
def extract_bid_workflow(workflow_id: str, request: Request, background_tasks: BackgroundTasks):
    user_id = current_user(request).id
    try:
        workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
        api_config_from_profile(user_id, workflow.provider_profile_id or "")
        if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
            raise ValueError("当前工作流正在执行中。")
        if workflow.status == BidWorkflowStatus.COMPLETED:
            raise ValueError("当前工作流已完成。")
        workflow = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.EXTRACTING)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流或模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "正在执行阶段一信息提取。")
    background_tasks.add_task(run_bid_extraction_task, user_id, workflow_id)
    return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="阶段一信息提取已开始。")


@app.post("/api/v1/bid-workflows/{workflow_id}/confirm", response_model=BidWorkflowActionResponse)
def confirm_bid_workflow(workflow_id: str, request: Request, payload: BidWorkflowConfirmRequest):
    user_id = current_user(request).id
    try:
        workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
        if not workflow.extracted_markdown:
            raise ValueError("请先完成阶段一信息提取。")
        if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
            raise ValueError("当前工作流正在执行中。")
        workflow = workbench_store.save_bid_confirmation(user_id, workflow_id, payload.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(user_id, workflow.conversation_id, "user", payload.text)
    try:
        save_behavior_report(user_id, workflow_id)
    except Exception as report_exc:
        print(f"[behavior-report] failed to save report on confirm for {workflow_id}: {report_exc}")
    return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="阶段一信息已确认。")


@app.post("/api/v1/bid-workflows/{workflow_id}/generate", response_model=BidWorkflowActionResponse)
def generate_bid_workflow(workflow_id: str, request: Request, payload: BidWorkflowGenerateRequest, background_tasks: BackgroundTasks):
    user_id = current_user(request).id
    try:
        workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
        api_config_from_profile(user_id, workflow.provider_profile_id or "")
        if not workflow.extracted_markdown:
            raise ValueError("请先完成阶段一信息提取。")
        if not workflow.confirmation_text:
            raise ValueError("请先确认阶段一信息。")
        if workflow.status in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
            raise ValueError("当前工作流正在执行中。")
        confirmation_text = workflow.confirmation_text
        if payload.extra_context:
            confirmation_text = f"{confirmation_text}\n\n补充信息：{payload.extra_context}"
        workbench_store.save_bid_confirmation(user_id, workflow_id, confirmation_text)
        workbench_store.save_bid_template_choice(user_id, workflow_id, "auto")
        if payload.extra_context:
            try:
                save_behavior_report(user_id, workflow_id)
            except Exception as report_exc:
                print(f"[behavior-report] failed to save report on generate for {workflow_id}: {report_exc}")
        workflow = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.GENERATING)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流或模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "正在按当前招标约束动态生成阶段二设计方案。")
    background_tasks.add_task(run_bid_generation_task, user_id, workflow_id)
    return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="阶段二设计方案生成已开始。")


@app.post("/api/v1/bid-workflows/{workflow_id}/cancel", response_model=BidWorkflowActionResponse)
def cancel_bid_workflow(workflow_id: str, request: Request):
    user_id = current_user(request).id
    try:
        workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
        if workflow.status == BidWorkflowStatus.COMPLETED:
            raise ValueError("当前工作流已完成，不能取消。")
        if workflow.status == BidWorkflowStatus.CANCELLED:
            return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="标书工作流已取消。")
        workflow = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.CANCELLED)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "当前标书流程已取消。")
    return BidWorkflowActionResponse(workflow=public_bid_workflow(workflow), message="标书工作流已取消。")


@app.get("/api/v1/bid-workflows/{workflow_id}/artifacts")
def list_bid_workflow_artifacts(workflow_id: str, request: Request):
    try:
        return workbench_store.list_bid_artifacts(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@app.get("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}")
def get_bid_workflow_artifact(workflow_id: str, name: str, request: Request):
    decoded = unquote(name)
    try:
        content = workbench_store.get_bid_artifact_content(current_user(request).id, workflow_id, decoded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果文件不存在。") from exc
    return Response(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(decoded)}"},
    )


@app.get("/api/v1/bid-workflows/{workflow_id}/export.zip")
def export_bid_workflow_zip(workflow_id: str, request: Request):
    try:
        files = workbench_store.get_bid_artifact_files(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc
    if not files:
        raise HTTPException(status_code=404, detail="暂无可导出的成果文件。")
    return Response(
        make_zip(files),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''bid-workflow-artifacts.zip"},
    )
