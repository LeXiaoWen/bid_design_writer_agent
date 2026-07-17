from fastapi import APIRouter, HTTPException, Query, Request

from ..schemas import (
    WorkbenchConversationCreate,
    WorkbenchConversationUpdate,
    WorkbenchProjectCreate,
    WorkbenchProjectUpdate,
)
from ..services.workbench_store import workbench_store
from .dependencies import current_user

router = APIRouter()


@router.get("/api/v1/projects")
def list_workbench_projects(request: Request):
    return workbench_store.list_projects(current_user(request).id)


@router.post("/api/v1/projects")
def create_workbench_project(request: Request, payload: WorkbenchProjectCreate):
    return workbench_store.create_project(current_user(request).id, payload)


@router.get("/api/v1/projects/{project_id}")
def get_workbench_project(project_id: str, request: Request):
    try:
        return workbench_store.get_project(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.patch("/api/v1/projects/{project_id}")
def update_workbench_project(project_id: str, request: Request, payload: WorkbenchProjectUpdate):
    try:
        return workbench_store.update_project(current_user(request).id, project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.delete("/api/v1/projects/{project_id}")
def delete_workbench_project(project_id: str, request: Request):
    try:
        workbench_store.delete_project(current_user(request).id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc
    return {"ok": True}


@router.get("/api/v1/conversations")
def list_workbench_conversations(request: Request, project_id: str | None = Query(default=None)):
    return workbench_store.list_conversations(current_user(request).id, project_id)


@router.post("/api/v1/conversations")
def create_workbench_conversation(request: Request, payload: WorkbenchConversationCreate):
    try:
        return workbench_store.create_conversation(current_user(request).id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在。") from exc


@router.get("/api/v1/conversations/{conversation_id}")
def get_workbench_conversation(conversation_id: str, request: Request):
    try:
        return workbench_store.get_conversation(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@router.patch("/api/v1/conversations/{conversation_id}")
def update_workbench_conversation(conversation_id: str, request: Request, payload: WorkbenchConversationUpdate):
    try:
        return workbench_store.update_conversation(current_user(request).id, conversation_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc


@router.delete("/api/v1/conversations/{conversation_id}")
def delete_workbench_conversation(conversation_id: str, request: Request):
    try:
        workbench_store.delete_conversation(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc
    return {"ok": True}


@router.get("/api/v1/conversations/{conversation_id}/messages")
def list_workbench_messages(conversation_id: str, request: Request):
    try:
        return workbench_store.list_messages(current_user(request).id, conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="对话不存在。") from exc
