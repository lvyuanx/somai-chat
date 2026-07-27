"""Tavily-backed web search client and LangChain tool adapter."""

from collections.abc import Mapping
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool


class TavilyClient:
    """Provider-neutral surface for the Tavily search endpoint."""

    def __init__(self, http_client: httpx.AsyncClient, *, api_key: str, max_results: int = 5) -> None:
        self._http_client = http_client
        self._api_key = api_key
        self._max_results = max_results

    async def search(self, query: str) -> Mapping[str, Any]:
        response = await self._http_client.post(
            "/search",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": self._max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results: list[dict[str, str]] = []
        if isinstance(raw_results, list):
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                title = item.get("title")
                url = item.get("url")
                content = item.get("content")
                if not all(isinstance(value, str) and value for value in (title, url, content)):
                    continue
                if isinstance(title, str) and isinstance(url, str) and isinstance(content, str):
                    results.append({"title": title[:300], "url": url[:2000], "content": content[:2000]})
        return {"query": query, "results": results}


def create_web_search_tool(client: TavilyClient) -> BaseTool:
    """Create a bounded search tool that hides upstream failure details."""

    @tool
    async def web_search(query: str) -> Mapping[str, Any]:
        """搜索互联网并返回带来源链接的摘要；适合查询实时或近期信息。"""
        normalized_query = query.strip()
        if not normalized_query:
            return {"error": "搜索关键词不能为空"}
        if len(normalized_query) > 500:
            return {"error": "搜索关键词过长"}
        try:
            return await client.search(normalized_query)
        except Exception:
            return {"error": "搜索服务暂时不可用，请稍后再试。"}

    return web_search
