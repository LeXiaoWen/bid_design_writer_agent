from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator
from uuid import uuid4

from openai import AsyncOpenAI

from ..schemas import ChatStreamRequest, WorkbenchConversationCreate
from .workbench_store import workbench_store


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"

_cancel_events: dict[str, asyncio.Event] = {}


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def cancel_run(run_id: str) -> bool:
    event = _cancel_events.get(run_id)
    if not event:
        return False
    event.set()
    return True


def _normalize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed_roles = {"system", "user", "assistant"}
    return [message for message in messages if message.get("role") in allowed_roles]


async def stream_chat(request: ChatStreamRequest) -> AsyncIterator[str]:
    profile = workbench_store.get_provider_profile(request.provider_profile_id) if request.provider_profile_id else None
    model = request.model or (profile.model if profile else DEFAULT_MODEL)
    base_url = profile.base_url if profile else DEFAULT_BASE_URL
    api_key = workbench_store.resolve_api_key(request.provider_profile_id, request.api_key)

    if not api_key:
        yield sse_event("error", {"type": "missing_api_key", "message": "请先配置 API key。"})
        return

    if request.conversation_id:
        conversation = workbench_store.get_conversation(request.conversation_id)
    else:
        conversation = workbench_store.create_conversation(
            WorkbenchConversationCreate(
                project_id=request.project_id,
                title=request.message.strip()[:32] or "新对话",
                provider_profile_id=request.provider_profile_id,
                model=model,
            )
        )

    previous_messages = workbench_store.list_messages(conversation.id)
    user_message = workbench_store.add_message(conversation.id, "user", request.message)
    assistant_message = workbench_store.add_message(conversation.id, "assistant", "", status="streaming", model=model)

    run_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[run_id] = cancel_event

    yield sse_event(
        "message_start",
        {
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "user_message_id": user_message.id,
            "run_id": run_id,
            "model": model,
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

    messages: list[dict[str, str]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
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
                workbench_store.update_message(assistant_message.id, final_content, "interrupted", finish_reason="cancelled")
                yield sse_event(
                    "message_done",
                    {
                        "conversation_id": conversation.id,
                        "message_id": assistant_message.id,
                        "status": "interrupted",
                        "finish_reason": "cancelled",
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
        workbench_store.update_message(assistant_message.id, final_content, "completed", finish_reason=finish_reason, usage=usage)
        yield sse_event(
            "message_done",
            {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "status": "completed",
                "finish_reason": finish_reason,
                "usage": usage,
                "content": final_content,
            },
        )
    except Exception as exc:
        final_content = "".join(content_parts)
        message = str(exc)
        workbench_store.update_message(assistant_message.id, final_content, "error", error=message)
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
