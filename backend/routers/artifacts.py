from urllib.parse import quote, unquote
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ..schemas import ArtifactContentUpdate, ArtifactSectionRewriteRequest, ArtifactVersion, ArtifactVersionContent, ArtifactVersionDiff
from ..services.artifacts import find_markdown_section, make_zip, replace_markdown_section
from ..services.workbench_store import workbench_store
from .dependencies import current_user


def create_router(
    *,
    api_config_from_profile: Callable[[str, str], Any],
    run_agent: Callable[[Any, str, str], str],
) -> APIRouter:
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


    @router.get("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}/versions/diff", response_model=ArtifactVersionDiff)
    def get_bid_workflow_artifact_version_diff(
        workflow_id: str,
        name: str,
        request: Request,
        base_version: int = Query(ge=1),
        compare_version: int = Query(ge=1),
    ):
        try:
            return workbench_store.get_bid_artifact_version_diff(
                current_user(request).id,
                workflow_id,
                unquote(name),
                base_version,
                compare_version,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="成果版本不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    @router.post("/api/v1/bid-workflows/{workflow_id}/artifacts/{name}/rewrite-section")
    def rewrite_bid_workflow_artifact_section(workflow_id: str, name: str, request: Request, payload: ArtifactSectionRewriteRequest):
        user_id = current_user(request).id
        try:
            workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
            if not workflow.provider_profile_id:
                raise ValueError("该工作流未关联模型配置，无法修改章节。")
            content = workbench_store.get_bid_artifact_content(user_id, workflow_id, unquote(name))
            section = find_markdown_section(content, payload.heading)
            api_config = api_config_from_profile(user_id, workflow.provider_profile_id)
            prompt = f"""请按用户要求重写以下标书章节的正文。只返回重写后的 Markdown 正文，不要输出标题、解释、前后缀或其他章节。不得编造招标事实；不确定的信息应明确标注待确认。

章节标题：{section.title}
用户要求：{payload.instruction.strip()}

当前章节正文：
{section.body or "（当前章节为空）"}
"""
            rewritten_body = run_agent(api_config, "你是建筑设计标书编辑助手，严格限定修改范围。", prompt)
            revised = replace_markdown_section(content, section, rewritten_body)
            return workbench_store.update_bid_artifact_content(user_id, workflow_id, unquote(name), revised)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="成果文件或模型配置不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    return router
