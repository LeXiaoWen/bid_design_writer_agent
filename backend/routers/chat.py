from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..schemas import ChatStreamRequest
from ..services.workbench_llm import cancel_run, stream_chat
from .dependencies import current_user

router = APIRouter()


@router.post("/api/v1/chat/stream")
async def stream_workbench_chat(request: Request, payload: ChatStreamRequest):
    return StreamingResponse(stream_chat(current_user(request).id, payload), media_type="text/event-stream")


@router.post("/api/v1/chat/{run_id}/cancel")
def cancel_workbench_chat(run_id: str, request: Request):
    return {"ok": cancel_run(current_user(request).id, run_id)}
