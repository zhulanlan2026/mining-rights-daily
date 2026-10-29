from __future__ import annotations

import asyncio
import os
from datetime import date

import pytest

from mining_rights_daily.agent.bus import open_bus
from mining_rights_daily.agent.orchestrator import generate_briefing
from mining_rights_daily.agent.protocol import unwrap_tool_result

QUERY = "给我生成一份关于 Pilbara 锂矿的今日简报"


@pytest.fixture(autouse=True)
def offline_news(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_ENABLE_LIVE", "0")


def test_news_server_lists_protocol_tool_names() -> None:
    from mining_rights_daily.servers.news import build_server

    async def _run() -> None:
        from mcp import Client

        async with Client(build_server()) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == {"search", "fetch_article"}
            result = await client.call_tool(
                "search",
                {"query": "Pilbara lithium", "days": 1, "as_of": "2026-10-27"},
            )
            payload = unwrap_tool_result(result)
            assert len(payload["items"]) == 2

    asyncio.run(_run())


def test_stdio_agent_writes_pilbara_briefing() -> None:
    async def _run() -> str:
        async with open_bus("stdio") as bus:
            return await generate_briefing(QUERY, bus, date(2026, 10, 27))

    # The child servers inherit the fixture env from this process.
    assert os.environ["NEWS_ENABLE_LIVE"] == "0"
    markdown = asyncio.run(_run())
    for heading in ("## 新闻摘要", "## 储量数据", "## 价格走势", "## 风险提示", "## 引用"):
        assert heading in markdown
    assert "日期：2026年10月27日（星期二）" in markdown
    assert "当天的新闻" in markdown
    assert "108.4" in markdown
    assert "53.1" in markdown
    assert "10460" in markdown
    assert "合成" in markdown
    assert "fixture://mining-rights-daily/news/pls-shipments-2026-10-27" in markdown
    assert "catalog:pilgangoora-ni43101-sample" in markdown
    assert "bundled-reference-series" in markdown
    assert "mining-news.search" in markdown
    assert "mineral-pdf.extract_resources" in markdown
    assert "lme-price.get_trend" in markdown
    assert "Copper concentrate" not in markdown
    assert "需要核对是否停产" not in markdown
    assert "承购" in markdown
