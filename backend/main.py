from datetime import datetime
import os
import re

from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from .schemas import (
    ApiConfig,
    BidWorkflow,
    BidWorkflowPublic,
    BidWorkflowStatus,
)
from .services.artifacts import build_output_files
from .services.app_version import get_app_version
from .services.auth import user_from_token
from .services.behavior_report import save_behavior_report
from .services.bid_jobs import BidJobWorker
from .services.config import API_PRESETS
from .services.credentials import CredentialStoreUnavailable
from .services.document_parser import parse_document
from .services.llm import run_agent
from .services.logging_config import configure_logging
from .services.skill_loader import (
    build_stage1_instructions,
    build_stage2_instructions,
    skill_source_label,
)
from .services.workbench_store import db_path, workbench_store
from .routers.auth import router as auth_router
from .routers.dependencies import bearer_token
from .routers.projects import router as projects_router
from .routers.config import router as config_router
from .routers.chat import router as chat_router
from .routers.bid_workflows import create_router as create_bid_workflows_router
from .routers.artifacts import router as artifacts_router

load_dotenv()
configure_logging()

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
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(config_router)
app.include_router(chat_router)
app.include_router(artifacts_router)


@app.exception_handler(CredentialStoreUnavailable)
async def credential_store_unavailable(_: Request, exc: CredentialStoreUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc), "code": "credential_store_unavailable"})

PUBLIC_API_V1_PATHS = {
    "/api/v1/auth/status",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
}


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


def bid_model_progress(job_id: str, stage: str):
    received_chars = 0
    reported_chars = 0
    workbench_store.update_bid_job(job_id, progress=15, message="正在建立模型连接。")

    def report(delta: str) -> None:
        nonlocal received_chars, reported_chars
        received_chars += len(delta)
        if received_chars < reported_chars + 200:
            return
        reported_chars = received_chars
        progress = min(90, 20 + received_chars // 100)
        workbench_store.update_bid_job(
            job_id,
            progress=progress,
            message=f"正在接收{stage}模型响应（{received_chars} 字）。",
        )

    return report


def run_bid_extraction_task(user_id: str, workflow_id: str, job_id: str | None = None) -> None:
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
        if job_id:
            result = run_agent(api_config, build_stage1_instructions(), prompt, on_delta=bid_model_progress(job_id, "阶段一"))
        else:
            result = run_agent(api_config, build_stage1_instructions(), prompt)
        if workflow_is_cancelled(user_id, workflow_id):
            return
        if job_id:
            workbench_store.update_bid_job(job_id, progress=92, message="正在整理阶段一提取结果。")
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


def run_bid_generation_task(user_id: str, workflow_id: str, job_id: str | None = None) -> None:
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
        if job_id:
            result = run_agent(api_config, build_stage2_instructions(), prompt, on_delta=bid_model_progress(job_id, "阶段二"))
        else:
            result = run_agent(api_config, build_stage2_instructions(), prompt)
        if workflow_is_cancelled(user_id, workflow_id):
            return
        if job_id:
            workbench_store.update_bid_job(job_id, progress=92, message="正在生成成果文件。")
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


def run_bid_job(job_id: str, user_id: str, workflow_id: str, kind: str) -> None:
    if kind == "extraction":
        run_bid_extraction_task(user_id, workflow_id, job_id)
        return
    if kind == "generation":
        run_bid_generation_task(user_id, workflow_id, job_id)
        return
    raise ValueError(f"未知标书任务类型：{kind}")


bid_job_worker = BidJobWorker(run_bid_job)


@app.on_event("startup")
def start_bid_job_worker() -> None:
    if os.getenv("AI_WORKBENCH_TEST_CREDENTIALS") != "1":
        bid_job_worker.start()


@app.on_event("shutdown")
def stop_bid_job_worker() -> None:
    bid_job_worker.stop()


def enqueue_bid_job(user_id: str, workflow_id: str, kind: str) -> BidWorkflow:
    workflow = workbench_store.enqueue_bid_job(user_id, workflow_id, kind)
    if os.getenv("AI_WORKBENCH_TEST_CREDENTIALS") == "1":
        bid_job_worker.run_pending()
    else:
        bid_job_worker.notify()
    return workbench_store.get_bid_workflow(user_id, workflow.id)


app.include_router(
    create_bid_workflows_router(
        api_config_from_profile=lambda user_id, profile_id: api_config_from_profile(user_id, profile_id),
        read_upload_with_limit=lambda file: read_upload_with_limit(file),
        parse_document=lambda file_name, content: parse_document(file_name, content),
        enqueue_bid_job=lambda user_id, workflow_id, kind: enqueue_bid_job(user_id, workflow_id, kind),
        public_bid_workflow=lambda workflow: public_bid_workflow(workflow),
        save_behavior_report=lambda user_id, workflow_id: save_behavior_report(user_id, workflow_id),
    )
)


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "ai-workbench-desktop",
        "version": get_app_version(),
        "skill_dir": skill_source_label(),
        "database": str(db_path()),
        "presets": API_PRESETS,
    }
