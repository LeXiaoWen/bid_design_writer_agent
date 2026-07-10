from __future__ import annotations

from openai import AsyncOpenAI

from ..schemas import ProviderModel
from .workbench_store import workbench_store


async def list_provider_models(user_id: str, profile_id: str) -> list[ProviderModel]:
    profile = workbench_store.get_provider_profile(user_id, profile_id)
    api_key = workbench_store.resolve_api_key(user_id, profile_id)
    if not api_key:
        raise ValueError("请先配置 API key。")

    client = AsyncOpenAI(api_key=api_key, base_url=profile.base_url or None)
    response = await client.models.list()
    models = []
    for item in response.data:
        model_id = getattr(item, "id", "")
        if model_id:
            models.append(ProviderModel(id=model_id, name=model_id))
    return sorted(models, key=lambda model: model.id.lower())
