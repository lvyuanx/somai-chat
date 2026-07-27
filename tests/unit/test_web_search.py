import json

import httpx
import pytest
from langchain_core.tools import BaseTool

from somai_chat.web.search import TavilyClient, create_web_search_tool


@pytest.mark.asyncio
async def test_web_search_tool_posts_bounded_query_and_returns_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.tavily.com/search"
        assert request.headers["authorization"] == "Bearer tavily-secret"
        assert json.loads(request.content) == {
            "query": "最新的 AI 新闻",
            "search_depth": "basic",
            "max_results": 2,
            "include_answer": False,
            "include_raw_content": False,
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "标题", "url": "https://example.com", "content": "摘要"},
                    {"title": "缺少链接", "content": "不要返回"},
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.tavily.com"
    ) as http_client:
        tool = create_web_search_tool(TavilyClient(http_client, api_key="tavily-secret", max_results=2))

        assert isinstance(tool, BaseTool)
        result = await tool.ainvoke({"query": "最新的 AI 新闻"})

    assert result == {
        "query": "最新的 AI 新闻",
        "results": [{"title": "标题", "url": "https://example.com", "content": "摘要"}],
    }


@pytest.mark.asyncio
async def test_web_search_tool_hides_upstream_failures() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private upstream detail")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.tavily.com"
    ) as http_client:
        tool = create_web_search_tool(TavilyClient(http_client, api_key="tavily-secret"))

        assert await tool.ainvoke({"query": "查询"}) == {"error": "搜索服务暂时不可用，请稍后再试。"}
