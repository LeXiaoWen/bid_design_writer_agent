from datetime import datetime
import asyncio
import json
import os
import re
import threading
from queue import Empty
from typing import AsyncIterator

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
from .services.bid_streams import bid_workflow_streams
from .services.config import API_PRESETS
from .services.credentials import CredentialStoreUnavailable
from .services.document_chunks import DOCUMENT_CHUNK_CHARACTER_BUDGET, split_document_text
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
from .routers.artifacts import create_router as create_artifacts_router

load_dotenv()
configure_logging()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
CHUNK_NOTE_CHARACTER_LIMIT = 4_000


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


def api_config_from_profile(user_id: str, provider_profile_id: str) -> ApiConfig:
    profile = workbench_store.get_provider_profile(user_id, provider_profile_id)
    api_key = workbench_store.resolve_api_key(user_id, provider_profile_id)
    if not api_key:
        raise ValueError("请先配置 API key。")
    return ApiConfig(provider=profile.provider, base_url=profile.base_url, api_key=api_key, model=profile.model)


def public_bid_workflow(workflow: BidWorkflow) -> BidWorkflowPublic:
    return BidWorkflowPublic.model_validate(workflow.model_dump(exclude={"file_text"}))


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def bid_message_start_payload(message) -> dict:
    return {
        "conversation_id": message.conversation_id,
        "message_id": message.id,
        "user_message_id": "",
        "run_id": message.id,
        "model": message.model or "",
        "usage": message.usage,
    }


def publish_bid_message_done(workflow_id: str, message, content: str, status: str, error: str | None = None) -> None:
    bid_workflow_streams.publish(
        workflow_id,
        "message_done",
        {
            "conversation_id": message.conversation_id,
            "message_id": message.id,
            "status": status,
            "content": content,
            "usage": message.usage,
            "error": error,
        },
    )


async def stream_bid_workflow_events(user_id: str, workflow_id: str) -> AsyncIterator[str]:
    workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
    subscriber = bid_workflow_streams.subscribe(workflow_id)
    try:
        messages = workbench_store.list_messages(user_id, workflow.conversation_id)
        message = next((item for item in reversed(messages) if item.role == "assistant" and item.status == "streaming"), None)
        if message:
            yield sse_event("message_start", bid_message_start_payload(message))
            if message.content:
                yield sse_event("message_update", {"conversation_id": message.conversation_id, "message_id": message.id, "content": message.content})
        while True:
            try:
                event, payload = await asyncio.to_thread(subscriber.get, True, 15)
            except Empty:
                current = workbench_store.get_bid_workflow(user_id, workflow_id)
                if current.status not in {BidWorkflowStatus.EXTRACTING, BidWorkflowStatus.GENERATING}:
                    return
                yield ": keepalive\n\n"
                continue
            yield sse_event(event, payload)
            if event == "message_done":
                return
    finally:
        bid_workflow_streams.unsubscribe(workflow_id, subscriber)


def workflow_is_cancelled(user_id: str, workflow_id: str) -> bool:
    return workbench_store.get_bid_workflow(user_id, workflow_id).status == BidWorkflowStatus.CANCELLED


def bid_model_progress(job_id: str, stage: str, initial_progress: int = 15):
    received_chars = 0
    reported_chars = 0
    lock = threading.Lock()
    response_started = threading.Event()
    stop_waiting = threading.Event()
    workbench_store.update_bid_job(job_id, progress=initial_progress, message="正在建立模型连接。")

    def report(delta: str) -> None:
        nonlocal received_chars, reported_chars
        with lock:
            response_started.set()
            received_chars += len(delta)
            if reported_chars and received_chars < reported_chars + 200:
                return
            reported_chars = received_chars
            progress = min(90, initial_progress + 5 + received_chars // 100)
            workbench_store.update_bid_job(
                job_id,
                progress=progress,
                message=f"正在接收{stage}模型响应（{received_chars} 字）。",
            )

    def report_waiting() -> None:
        elapsed = 0
        while True:
            if stop_waiting.wait(5):
                return
            elapsed += 5
            with lock:
                if response_started.is_set():
                    return
                workbench_store.update_bid_job(
                    job_id,
                    progress=min(initial_progress + 4, initial_progress + elapsed // 5),
                    message=f"正在等待{stage}模型响应（已等待 {elapsed} 秒）。",
                )

    threading.Thread(target=report_waiting, name=f"bid-model-progress-{job_id}", daemon=True).start()
    return report, stop_waiting.set


def bid_usage(instructions: str, prompt: str, output: str = "") -> dict[str, int | str]:
    context_characters = len(instructions) + len(prompt)
    completion_characters = len(output)
    context_tokens = (context_characters + 3) // 4
    completion_tokens = (completion_characters + 3) // 4
    return {
        "usage_source": "estimated",
        "context_characters": context_characters,
        "context_estimated_tokens": context_tokens,
        "completion_estimated_tokens": completion_tokens,
        "total_estimated_tokens": context_tokens + completion_tokens,
    }


def compact_chunk_notes(user_id: str, workflow_id: str, api_config: ApiConfig, notes: list[str], job_id: str | None) -> str | None:
    while len(_numbered_chunk_notes(notes)) > DOCUMENT_CHUNK_CHARACTER_BUDGET:
        groups = split_document_text(_numbered_chunk_notes(notes))
        condensed_notes = []
        for index, group in enumerate(groups, start=1):
            if workflow_is_cancelled(user_id, workflow_id):
                return None
            if job_id:
                progress = 70 + (index - 1) * 4 // len(groups)
                workbench_store.update_bid_job(job_id, progress=progress, message=f"正在压缩第 {index}/{len(groups)} 组分块笔记。")
            condensed_notes.append(
                run_agent(
                    api_config,
                    """你负责合并招标文件的分块事实笔记。去除重复，但必须保留项目名称、范围、时间、金额、评分、成果、格式、资格、风险和否定条件；不要补全信息，控制在 4,000 字以内。""",
                    f"请合并以下分块事实笔记：\n\n{group}",
                )[:CHUNK_NOTE_CHARACTER_LIMIT]
            )
        notes = condensed_notes
    return _numbered_chunk_notes(notes)


def _numbered_chunk_notes(notes: list[str]) -> str:
    return "\n\n".join(
        f"--- 分块 {index} 提取笔记 ---\n{note}"
        for index, note in enumerate(notes, start=1)
    )


def run_bid_agent_stream(
    user_id: str,
    workflow_id: str,
    conversation_id: str,
    message_id: str,
    job_id: str,
    stage: str,
    api_config: ApiConfig,
    instructions: str,
    prompt: str,
    initial_progress: int = 15,
) -> str:
    chunks: list[str] = []
    published_length = 0
    report_progress, stop_progress = bid_model_progress(job_id, stage, initial_progress)

    def on_delta(delta: str) -> None:
        nonlocal published_length
        chunks.append(delta)
        report_progress(delta)
        content = "".join(chunks)
        bid_workflow_streams.publish(
            workflow_id,
            "message_update",
            {"conversation_id": conversation_id, "message_id": message_id, "content": content},
        )
        if len(content) - published_length < 24:
            return
        published_length = len(content)
        workbench_store.update_streaming_message(user_id, message_id, content)

    try:
        result = run_agent(api_config, instructions, prompt, on_delta=on_delta)
        if result and result != "".join(chunks):
            workbench_store.update_streaming_message(user_id, message_id, result)
            bid_workflow_streams.publish(workflow_id, "message_update", {"conversation_id": conversation_id, "message_id": message_id, "content": result})
        elif len("".join(chunks)) > published_length:
            workbench_store.update_streaming_message(user_id, message_id, "".join(chunks))
        return result
    finally:
        stop_progress()


def run_bid_extraction_task(user_id: str, workflow_id: str, job_id: str | None = None) -> None:
    workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
    assistant_message = None
    stream_usage = None
    try:
        if workflow.status == BidWorkflowStatus.CANCELLED:
            return
        api_config = api_config_from_profile(user_id, workflow.provider_profile_id or "")
        instructions = build_stage1_instructions()
        chunks = split_document_text(workflow.file_text)
        initial_progress = 15
        if len(chunks) == 1:
            source_material = workflow.file_text
        else:
            partial_notes = []
            for index, chunk in enumerate(chunks, start=1):
                if workflow_is_cancelled(user_id, workflow_id):
                    return
                if job_id:
                    progress = 15 + (index - 1) * 60 // len(chunks)
                    workbench_store.update_bid_job(job_id, progress=progress, message=f"正在解析招标文件第 {index}/{len(chunks)} 块。")
                partial_notes.append(
                    run_agent(
                        api_config,
                        """你负责提炼招标文件分块中的可核验事实。仅依据当前分块，紧凑记录项目名称、范围、时间、金额、评分、成果、格式、资格和风险要求；保留原始数值与否定条件。不要编写方案，不要补全缺失信息，控制在 4,000 字以内。""",
                        f"""招标文件：{workflow.file_name}
这是第 {index}/{len(chunks)} 个分块。请提炼该分块的事实笔记：

{chunk}""",
                    )[:CHUNK_NOTE_CHARACTER_LIMIT]
                )
            source_material = compact_chunk_notes(user_id, workflow_id, api_config, partial_notes, job_id)
            if source_material is None:
                return
            initial_progress = 75

        prompt = f"""
请执行阶段一：从以下招标文件文本或分块事实笔记中提取四类关键信息，并按 Skill 要求输出。

文件名：{workflow.file_name}
提取时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}

招标文件内容：
{source_material}
"""
        if job_id:
            stream_usage = bid_usage(instructions, prompt)
            assistant_message = workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "", status="streaming", model=api_config.model, usage=stream_usage)
            bid_workflow_streams.publish(workflow_id, "message_start", bid_message_start_payload(assistant_message))
            result = run_bid_agent_stream(
                user_id,
                workflow_id,
                workflow.conversation_id,
                assistant_message.id,
                job_id,
                "阶段一",
                api_config,
                instructions,
                prompt,
                initial_progress,
            )
        else:
            result = run_agent(api_config, instructions, prompt)
        if workflow_is_cancelled(user_id, workflow_id):
            if assistant_message:
                saved_message = workbench_store.update_message(user_id, assistant_message.id, result, "interrupted", finish_reason="cancelled", usage=bid_usage(instructions, prompt, result))
                publish_bid_message_done(workflow_id, saved_message, result, "interrupted")
            return
        if job_id:
            workbench_store.update_bid_job(job_id, progress=92, message="正在整理阶段一提取结果。")
        saved = workbench_store.save_bid_extraction(user_id, workflow_id, result)
        content = f"{result}\n\n请确认以上信息是否准确。确认后可进入阶段二生成设计方案。"
        if assistant_message:
            saved_message = workbench_store.update_message(user_id, assistant_message.id, content, "completed", usage=bid_usage(instructions, prompt, result))
            publish_bid_message_done(workflow_id, saved_message, content, "completed")
        else:
            workbench_store.add_message(user_id, saved.conversation_id, "assistant", content)
    except Exception as exc:
        failed = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.FAILED, error=str(exc))
        if assistant_message:
            partial_content = workbench_store.get_message(user_id, assistant_message.id).content
            saved_message = workbench_store.update_message(user_id, assistant_message.id, partial_content, "error", usage=stream_usage, error=str(exc))
            publish_bid_message_done(workflow_id, saved_message, partial_content, "error", str(exc))
        else:
            workbench_store.add_message(user_id, failed.conversation_id, "assistant", f"阶段一提取失败：{exc}", status="error", error=str(exc))


def run_bid_generation_task(user_id: str, workflow_id: str, job_id: str | None = None) -> None:
    workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
    assistant_message = None
    stream_usage = None
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
        instructions = build_stage2_instructions()
        if job_id:
            stream_usage = bid_usage(instructions, prompt)
            assistant_message = workbench_store.add_message(user_id, workflow.conversation_id, "assistant", "", status="streaming", model=api_config.model, usage=stream_usage)
            bid_workflow_streams.publish(workflow_id, "message_start", bid_message_start_payload(assistant_message))
            result = run_bid_agent_stream(user_id, workflow_id, workflow.conversation_id, assistant_message.id, job_id, "阶段二", api_config, instructions, prompt)
        else:
            result = run_agent(api_config, instructions, prompt)
        if workflow_is_cancelled(user_id, workflow_id):
            if assistant_message:
                saved_message = workbench_store.update_message(user_id, assistant_message.id, result, "interrupted", finish_reason="cancelled", usage=bid_usage(instructions, prompt, result))
                publish_bid_message_done(workflow_id, saved_message, result, "interrupted")
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
        content = f"{result}\n\n生成完成，可下载 Markdown 文件或 ZIP 包。"
        if assistant_message:
            saved_message = workbench_store.update_message(user_id, assistant_message.id, content, "completed", usage=bid_usage(instructions, prompt, result))
            publish_bid_message_done(workflow_id, saved_message, content, "completed")
        else:
            workbench_store.add_message(user_id, completed.conversation_id, "assistant", content)
    except Exception as exc:
        failed = workbench_store.update_bid_workflow_status(user_id, workflow_id, BidWorkflowStatus.FAILED, error=str(exc))
        if assistant_message:
            partial_content = workbench_store.get_message(user_id, assistant_message.id).content
            saved_message = workbench_store.update_message(user_id, assistant_message.id, partial_content, "error", usage=stream_usage, error=str(exc))
            publish_bid_message_done(workflow_id, saved_message, partial_content, "error", str(exc))
        else:
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
        stream_bid_events=lambda user_id, workflow_id: stream_bid_workflow_events(user_id, workflow_id),
    )
)
app.include_router(
    create_artifacts_router(
        api_config_from_profile=lambda user_id, profile_id: api_config_from_profile(user_id, profile_id),
        run_agent=lambda api_config, instructions, prompt: run_agent(api_config, instructions, prompt),
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
