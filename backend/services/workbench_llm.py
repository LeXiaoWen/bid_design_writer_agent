from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from uuid import uuid4

from openai import AsyncOpenAI

from ..schemas import BidWorkflowStatus, ChatStreamRequest, WorkbenchConversationCreate
from .behavior_report import save_behavior_report
from .logging_config import redact_log_text
from .web_search import build_search_context, tavily_search
from .workbench_store import workbench_store


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"
CONTEXT_CHARACTER_BUDGET = 24_000
RECENT_CONTEXT_MESSAGES = 12

_cancel_events: dict[str, tuple[str, asyncio.Event]] = {}
logger = logging.getLogger("bid_design_writer.chat")


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def cancel_run(user_id: str, run_id: str) -> bool:
    stored = _cancel_events.get(run_id)
    if not stored or stored[0] != user_id:
        return False
    event = stored[1]
    event.set()
    return True


def _normalize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed_roles = {"system", "user", "assistant"}
    return [message for message in messages if message.get("role") in allowed_roles]


def _build_context_summary(existing: str, messages: list[Any]) -> str:
    lines = [existing] if existing else []
    for message in messages:
        content = " ".join(message.content.split())
        if content:
            lines.append(f"{message.role}: {content[:800]}")
    # Keep enough room for the live context while retaining durable decisions.
    return "\n".join(lines)[-8_000:]


def _context_characters(summary: str, messages: list[Any], pending_message: str = "") -> int:
    return len(summary) + len(pending_message) + sum(len(message.content) for message in messages)


def _context_usage(characters: int) -> dict[str, int]:
    return {
        "context_characters": characters,
        "context_budget": CONTEXT_CHARACTER_BUDGET,
        "context_estimated_tokens": (characters + 3) // 4,
    }


def _merge_usage(context_usage: dict[str, int], provider_usage: dict[str, Any] | None) -> dict[str, Any]:
    return {**context_usage, **(provider_usage or {})}


def _build_context_window(existing_summary: str, previous_messages: list[Any], pending_message: str) -> tuple[str, list[Any], bool]:
    if _context_characters(existing_summary, previous_messages, pending_message) <= CONTEXT_CHARACTER_BUDGET:
        return existing_summary, previous_messages, False

    archived_messages = list(previous_messages[:-RECENT_CONTEXT_MESSAGES])
    recent_messages = list(previous_messages[-RECENT_CONTEXT_MESSAGES:])
    summary = _build_context_summary(existing_summary, archived_messages)
    while recent_messages and _context_characters(summary, recent_messages, pending_message) > CONTEXT_CHARACTER_BUDGET:
        archived_messages.append(recent_messages.pop(0))
        summary = _build_context_summary(existing_summary, archived_messages)

    available_summary_characters = max(CONTEXT_CHARACTER_BUDGET - len(pending_message), 0)
    summary = summary[-available_summary_characters:] if available_summary_characters else ""
    return summary, recent_messages, True


async def stream_chat(user_id: str, request: ChatStreamRequest) -> AsyncIterator[str]:
    profile = workbench_store.get_provider_profile(user_id, request.provider_profile_id) if request.provider_profile_id else None
    model = request.model or (profile.model if profile else DEFAULT_MODEL)
    base_url = profile.base_url if profile else DEFAULT_BASE_URL
    api_key = workbench_store.resolve_api_key(user_id, request.provider_profile_id, request.api_key)

    if not api_key:
        yield sse_event("error", {"type": "missing_api_key", "message": "请先配置 API key。"})
        return

    if request.conversation_id:
        conversation = workbench_store.get_conversation(user_id, request.conversation_id)
    else:
        conversation = workbench_store.create_conversation(
            user_id,
            WorkbenchConversationCreate(
                project_id=request.project_id,
                title=request.message.strip()[:32] or "新对话",
                provider_profile_id=request.provider_profile_id,
                model=model,
            )
        )

    previous_messages = workbench_store.list_messages(user_id, conversation.id)
    context_summary = workbench_store.get_context_summary(user_id, conversation.id)
    context_summary, previous_messages, summary_updated = _build_context_window(context_summary, previous_messages, request.message)
    if summary_updated:
        workbench_store.set_context_summary(user_id, conversation.id, context_summary)
    context_usage = _context_usage(_context_characters(context_summary, previous_messages, request.message))
    user_message = workbench_store.add_message(user_id, conversation.id, "user", request.message)

    # 若该对话存在标书工作流，用户每条消息都保存行为摘要
    bid_workflows = workbench_store.list_bid_workflows(user_id, conversation.id)
    active_workflow_ids = [
        wf.id
        for wf in bid_workflows
        if wf.status
        in {
            BidWorkflowStatus.EXTRACTING,
            BidWorkflowStatus.EXTRACTION_READY,
            BidWorkflowStatus.GENERATING,
            BidWorkflowStatus.COMPLETED,
        }
    ]
    if active_workflow_ids:
        try:
            save_behavior_report(user_id, active_workflow_ids[0])
        except Exception:
            logger.warning("failed to save behavior report", extra={"workflow_id": active_workflow_ids[0], "user_id": user_id}, exc_info=True)

    assistant_message = workbench_store.add_message(user_id, conversation.id, "assistant", "", status="streaming", model=model, usage=context_usage)

    run_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[run_id] = (user_id, cancel_event)

    yield sse_event(
        "message_start",
        {
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "user_message_id": user_message.id,
            "run_id": run_id,
            "model": model,
            "usage": context_usage,
        },
    )

    if len(previous_messages) == 0:
        yield sse_event(
            "conversation_updated",
            {
                "conversation_id": conversation.id,
                "title": conversation.title,
                "project_id": conversation.project_id,
            },
        )

    system_parts: list[str] = []
    if request.system_prompt:
        system_parts.append(request.system_prompt)
    if context_summary:
        system_parts.append(f"以下是较早对话的持久化摘要，请将其作为上下文，不要逐字复述：\n{context_summary}")
    if request.web_search_enabled:
        try:
            search_results = await tavily_search(user_id, request.message)
            system_parts.append(build_search_context(search_results))
        except Exception as exc:
            message = str(exc)
            system_parts.append(f"（联网搜索暂时不可用：{message}。请基于已有知识回答，并提示用户稍后重试。）")
            yield sse_event(
                "warning",
                {
                    "conversation_id": conversation.id,
                    "message_id": assistant_message.id,
                    "type": exc.__class__.__name__,
                    "message": message,
                },
            )

    if system_parts:
        messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
    else:
        messages = []
    messages.extend({"role": message.role, "content": message.content} for message in previous_messages if message.status != "error")
    messages.append({"role": "user", "content": request.message})
    messages = _normalize_messages(messages)

    content_parts: list[str] = []
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
        stream = await client.chat.completions.create(model=model, messages=messages, stream=True)
        async for chunk in stream:
            if cancel_event.is_set():
                final_content = "".join(content_parts)
                workbench_store.update_message(user_id, assistant_message.id, final_content, "interrupted", finish_reason="cancelled", usage=context_usage)
                yield sse_event(
                    "message_done",
                    {
                        "conversation_id": conversation.id,
                        "message_id": assistant_message.id,
                        "status": "interrupted",
                        "finish_reason": "cancelled",
                        "usage": context_usage,
                        "content": final_content,
                    },
                )
                return

            if chunk.usage:
                usage = chunk.usage.model_dump()
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = getattr(choice.delta, "content", None)
            if not delta:
                continue
            content_parts.append(delta)
            yield sse_event("delta", {"conversation_id": conversation.id, "message_id": assistant_message.id, "delta": delta})

        final_content = "".join(content_parts)
        merged_usage = _merge_usage(context_usage, usage)
        workbench_store.update_message(user_id, assistant_message.id, final_content, "completed", finish_reason=finish_reason, usage=merged_usage)
        yield sse_event(
            "message_done",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "status": "completed",
                "finish_reason": finish_reason,
                "usage": merged_usage,
                "content": final_content,
            },
        )
    except Exception as exc:
        final_content = "".join(content_parts)
        message = redact_log_text(str(exc))
        workbench_store.update_message(user_id, assistant_message.id, final_content, "error", usage=context_usage, error=message)
        yield sse_event(
            "error",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "type": exc.__class__.__name__,
                "message": message,
                "content": final_content,
            },
        )
    finally:
        _cancel_events.pop(run_id, None)
