from fastapi import APIRouter, HTTPException, Query, Request

from ..schemas import ProviderModelsResponse, ProviderProfileCreate, ProviderProfileUpdate, WebSearchConfig, WebSearchConfigUpdate
from ..services.provider_models import list_provider_models as fetch_provider_models
from ..services.logging_config import redact_log_text
from ..services.workbench_store import workbench_store
from .dependencies import current_user

router = APIRouter()


@router.get("/api/v1/provider-profiles")
def list_provider_profiles(request: Request):
    return workbench_store.list_provider_profiles(current_user(request).id)


@router.post("/api/v1/provider-profiles")
def create_provider_profile(request: Request, payload: ProviderProfileCreate):
    return workbench_store.create_provider_profile(current_user(request).id, payload)


@router.get("/api/v1/provider-profiles/{profile_id}/models", response_model=ProviderModelsResponse)
async def list_provider_models(profile_id: str, request: Request):
    try:
        models = await fetch_provider_models(current_user(request).id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型列表拉取失败：{redact_log_text(str(exc))}") from exc
    return ProviderModelsResponse(models=models)


@router.patch("/api/v1/provider-profiles/{profile_id}")
def update_provider_profile(profile_id: str, request: Request, payload: ProviderProfileUpdate):
    try:
        return workbench_store.update_provider_profile(current_user(request).id, profile_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc


@router.delete("/api/v1/provider-profiles/{profile_id}")
def delete_provider_profile(profile_id: str, request: Request):
    try:
        workbench_store.delete_provider_profile(current_user(request).id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在。") from exc
    return {"ok": True}


@router.get("/api/v1/search")
def search_workbench(request: Request, q: str = Query(default=""), kind: str = Query(default="")):
    if kind and kind not in {"project", "conversation", "message"}:
        raise HTTPException(status_code=422, detail="kind 只能是 project、conversation 或 message。")
    return workbench_store.search(current_user(request).id, q, kind or None)


@router.get("/api/v1/web-search-config", response_model=WebSearchConfig)
def get_web_search_config(request: Request):
    return workbench_store.get_web_search_config(current_user(request).id)


@router.patch("/api/v1/web-search-config", response_model=WebSearchConfig)
def update_web_search_config(request: Request, payload: WebSearchConfigUpdate):
    return workbench_store.update_web_search_config(current_user(request).id, payload)
