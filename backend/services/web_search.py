from __future__ import annotations

from dataclasses import dataclass
import os

import httpx

from .workbench_store import workbench_store


DEFAULT_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 20
BASIC_CONTENT_LIMIT = 900
ADVANCED_CONTENT_LIMIT = 2000


class WebSearchNotConfiguredError(ValueError):
    pass


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    content: str


def _shorten(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def _timeout_seconds() -> float:
    raw = os.getenv("TAVILY_SEARCH_TIMEOUT", "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return float(DEFAULT_TIMEOUT_SECONDS)


async def tavily_search(user_id: str, query: str) -> list[WebSearchResult]:
    config = workbench_store.get_web_search_config(user_id)
    api_key = workbench_store.resolve_tavily_api_key(user_id)
    if not api_key:
        raise WebSearchNotConfiguredError("未配置 TAVILY_API_KEY，无法使用联网搜索。")

    endpoint = os.getenv("TAVILY_SEARCH_URL", DEFAULT_TAVILY_SEARCH_URL).strip() or DEFAULT_TAVILY_SEARCH_URL
    content_limit = ADVANCED_CONTENT_LIMIT if config.search_depth == "advanced" else BASIC_CONTENT_LIMIT
    payload = {
        "query": query,
        "search_depth": config.search_depth,
        "max_results": config.max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    results: list[WebSearchResult] = []
    for item in data.get("results", []):
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        content = str(item.get("content") or "").strip()
        if not title and not url and not content:
            continue
        results.append(WebSearchResult(title=title or url, url=url, content=_shorten(content, limit=content_limit)))
    return results


def build_search_context(results: list[WebSearchResult]) -> str:
    if not results:
        return "Tavily 未返回可用搜索结果。"

    lines = [
        "以下是 Tavily 联网搜索结果。回答时优先使用这些信息；如使用结果中的事实，请用 [1]、[2] 这样的编号标注来源。",
        "",
    ]
    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                f"[{index}] {result.title}",
                f"URL: {result.url}",
                f"摘要: {result.content or '无摘要'}",
                "",
            ]
        )
    return "\n".join(lines).strip()
