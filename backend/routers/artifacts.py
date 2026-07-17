from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ..schemas import ArtifactContentUpdate, ArtifactVersion, ArtifactVersionContent
from ..services.artifacts import make_zip
from ..services.workbench_store import workbench_store
from .dependencies import current_user

router = APIRouter()


@router.get("/api/v1/bid-workflows/{workflow_id}/artifacts")
def list_bid_workflow_artifacts(workflow_id: str, request: Request):
    try:
        return workbench_store.list_bid_artifacts(current_user(request).id, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@router.get("/api/v1/bid-workflows/{workflow_id}/artifacts/versions", response_model=list[ArtifactVersion])
def list_bid_workflow_artifact_versions(workflow_id: str, request: Request, name: str | None = Query(default=None)):
    try:
        return workbench_store.list_bid_artifact_versions(current_user(request).id, workflow_id, name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="标书工作流不存在。") from exc


@router.post("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}/versions/{version}/restore")
def restore_bid_workflow_artifact_version(workflow_id: str, name: str, version: int, request: Request):
    try:
        workbench_store.restore_bid_artifact_version(current_user(request).id, workflow_id, unquote(name), version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果版本不存在。") from exc
    return {"ok": True}


@router.get("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}/versions/{version}", response_model=ArtifactVersionContent)
def get_bid_workflow_artifact_version(workflow_id: str, name: str, version: int, request: Request):
    try:
        return workbench_store.get_bid_artifact_version(current_user(request).id, workflow_id, unquote(name), version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果版本不存在。") from exc


@router.patch("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}")
def update_bid_workflow_artifact(workflow_id: str, name: str, request: Request, payload: ArtifactContentUpdate):
    try:
        return workbench_store.update_bid_artifact_content(current_user(request).id, workflow_id, unquote(name), payload.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="成果文件不存在。") from exc


@router.get("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}")
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


@router.get("/api/v1/bid-workflows/{workflow_id}/export.zip")
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
