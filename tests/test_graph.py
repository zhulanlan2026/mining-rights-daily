from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest

from mining_rights_daily.agent.graph.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from mining_rights_daily.agent.graph.deepseek import DeepSeekClient, unsupported_numbers
from mining_rights_daily.agent.graph.run import run_turn
from mining_rights_daily.agent.protocol import ToolCallError
from mining_rights_daily.agent.sse import format_sse, start_sse

QUERY = "生成 Pilbara 锂矿今日简报"
DAY = date(2026, 10, 27)

_SEARCH = {
    "items": [
        {
            "title": "PLS ships",
            "url": "fixture://news/1",
            "snippet": "offtake",
            "source": "fixture",
            "source_type": "fixture",
            "published_at": "2026-10-27",
        }
    ],
    "query": "pilbara lithium",
    "window_start": "2026-10-27",
    "as_of": "2026-10-27",
    "days": 1,
}
_PAYLOADS = {
    ("mining-news", "search"): _SEARCH,
    ("mining-news", "fetch_article"): {"url": "fixture://news/1", "text": "offtake agreement signed"},
    ("mineral-pdf", "extract_resources"): {
        "project": "Pilgangoora",
        "location": "WA",
        "standard": "NI 43-101",
        "effective_date": "2026-01-01",
        "pdf_url": "catalog:pilgangoora-ni43101-sample",
        "is_synthetic": True,
        "rows": [
            {
                "kind": "resource",
                "category": "Indicated",
                "tonnes_mt": 108.4,
                "grade_pct": 1.2,
                "grade_label": "% Li2O",
                "contained_kt": 10,
                "contained_label": "kt",
            },
            {
                "kind": "resource",
                "category": "Inferred",
                "tonnes_mt": 53.1,
                "grade_pct": 1.1,
                "grade_label": "% Li2O",
            },
        ],
    },
    ("lme-price", "get_price"): {
        "contract": "lithium hydroxide",
        "source": "bundled-reference-series",
        "requested_date": "2026-10-27",
        "resolved_date": "2026-10-27",
        "close": 10460,
        "unit": "USD/t",
        "disclaimer": "不是 LME 结算价",
        "day_change_pct": -1,
    },
    ("lme-price", "get_trend"): {
        "direction": "down",
        "change_pct": -6,
        "days": 30,
        "start_date": "2026-09-01",
        "end_date": "2026-10-27",
        "start": 11000,
        "end": 10460,
        "unit": "USD/t",
        "high": 12000,
        "low": 10000,
        "points": [{"date": "2026-10-27", "close": 10460}],
    },
}


class FakeBus:
    def __init__(self, fail: set[tuple[str, str]] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[tuple[str, str, dict]] = []

    async def call(self, server: str, tool: str, arguments):
        self.calls.append((server, tool, dict(arguments)))
        if (server, tool) in self.fail:
            raise ToolCallError(f"{server}.{tool} 不可用")
        return json.loads(json.dumps(_PAYLOADS[(server, tool)]))


class ScriptedModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        del system, user
        self.calls += 1
        return self.reply


@pytest.fixture(autouse=True)
def no_deepseek_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def test_daily_report_calls_tools_in_order(tmp_path) -> None:
    bus = FakeBus()
    markdown = asyncio.run(run_turn(QUERY, DAY, bus, tmp_path / "mem.sqlite", "daily"))
    assert [(server, tool) for server, tool, _ in bus.calls] == [
        ("mining-news", "search"),
        ("mining-news", "fetch_article"),
        ("mineral-pdf", "extract_resources"),
        ("lme-price", "get_price"),
        ("lme-price", "get_trend"),
    ]
    assert bus.calls[2][2]["pdf_url"] == "catalog:pilgangoora-ni43101-sample"
    for heading in ("## 新闻摘要", "## 储量数据", "## 价格走势", "## 风险提示", "## 引用"):
        assert heading in markdown
    assert "fixture://news/1" in markdown
    assert "10460" in markdown


def test_daily_report_matches_scripted_renderer(tmp_path) -> None:
    from mining_rights_daily.agent.orchestrator import generate_briefing

    async def both() -> tuple[str, str]:
        graph = await run_turn(QUERY, DAY, FakeBus(), tmp_path / "mem.sqlite", "same")
        scripted = await generate_briefing(QUERY, FakeBus(), DAY)
        return graph, scripted

    graph, scripted = asyncio.run(both())
    assert graph == scripted


def test_price_query_stays_out_of_the_daily_report(tmp_path) -> None:
    bus = FakeBus()
    markdown = asyncio.run(run_turn("查一下今天的锂价", DAY, bus, tmp_path / "mem.sqlite", "price"))
    assert [(server, tool) for server, tool, _ in bus.calls] == [("lme-price", "get_price")]
    assert "10460" in markdown
    assert "不是 LME 结算价" in markdown
    assert "## 储量数据" not in markdown
    assert "## 新闻摘要" not in markdown


def test_failed_price_tool_does_not_stop_the_report(tmp_path) -> None:
    bus = FakeBus(fail={("lme-price", "get_price"), ("lme-price", "get_trend")})
    markdown = asyncio.run(run_turn(QUERY, DAY, bus, tmp_path / "mem.sqlite", "down"))
    assert "未获取到数据" in markdown
    assert "catalog:pilgangoora-ni43101-sample" in markdown
    assert "## 新闻摘要" in markdown
    assert any(call[0] == "mineral-pdf" for call in bus.calls)


def test_same_thread_recalls_the_previous_report(tmp_path) -> None:
    bus = FakeBus()
    path = tmp_path / "mem.sqlite"
    first = asyncio.run(run_turn(QUERY, DAY, bus, path, "thread-a"))
    assert "2026年10月27日" in first
    bus.calls.clear()
    second = asyncio.run(run_turn("上一轮简报是哪一天", DAY, bus, path, "thread-a"))
    assert "2026年10月27日" in second
    assert bus.calls == []


def test_unknown_query_asks_for_clarification(tmp_path) -> None:
    bus = FakeBus()
    markdown = asyncio.run(run_turn("你好", DAY, bus, tmp_path / "mem.sqlite", "hi"))
    assert "请说明要查的内容" in markdown
    assert bus.calls == []


def test_deepseek_can_upgrade_an_unclear_query(tmp_path) -> None:
    bus = FakeBus()
    model = ScriptedModel('{"intent":"generate_daily_report"}')
    markdown = asyncio.run(
        run_turn("Pilbara 锂", DAY, bus, tmp_path / "mem.sqlite", "llm", deepseek=model)
    )
    assert model.calls >= 1
    assert any(call[1] == "extract_resources" for call in bus.calls)
    assert "catalog:pilgangoora-ni43101-sample" in markdown


def test_deepseek_judgment_drops_unknown_numbers(tmp_path) -> None:
    bus = FakeBus()
    model = ScriptedModel("价格是 99999。")
    markdown = asyncio.run(run_turn(QUERY, DAY, bus, tmp_path / "mem.sqlite", "judge", deepseek=model))
    assert "99999" not in markdown
    assert "已丢弃" in markdown
    assert "10460" in markdown


def test_stream_ends_with_the_report(tmp_path) -> None:
    from mining_rights_daily.agent.graph.run import stream_turn

    async def collect() -> list[dict[str, str]]:
        events = []
        async for event in stream_turn(QUERY, DAY, FakeBus(), tmp_path / "mem.sqlite", "stream"):
            events.append(event)
        return events

    events = asyncio.run(collect())
    assert any(event.get("node") == "intent" for event in events)
    assert events[-1]["event"] == "report"
    assert "## 价格走势" in events[-1]["markdown"]


def test_sse_frame_and_endpoint() -> None:
    assert format_sse("report", "第一行\n第二行").startswith("event: report\n")

    async def scenario() -> None:
        async def producer(query: str, as_of: date, thread_id: str):
            del as_of, thread_id
            yield {"event": "node", "node": "intent"}
            yield {"event": "report", "markdown": f"# {query}\n"}

        server = await start_sse("127.0.0.1", 0, producer)
        port = server.sockets[0].getsockname()[1]
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://127.0.0.1:{port}/v1/briefing",
                    params={"query": "生成简报"},
                )
        finally:
            server.close()
            await server.wait_closed()
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "event: report" in response.text
        assert "生成简报" in response.text

    asyncio.run(scenario())


def test_deepseek_request_uses_chat_model() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def call() -> str:
        client = DeepSeekClient.from_env(transport=httpx.MockTransport(handler))
        assert client is not None
        return await client.complete("系统", "用户")

    monkey = pytest.MonkeyPatch()
    monkey.setenv("DEEPSEEK_API_KEY", "test-key")
    monkey.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkey.delenv("DEEPSEEK_MODEL", raising=False)
    try:
        assert asyncio.run(call()) == "ok"
    finally:
        monkey.undo()
    assert seen["url"] == f"{DEEPSEEK_BASE_URL}/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == DEEPSEEK_MODEL
    assert unsupported_numbers("价格是 99999", "收盘 10460") == ["99999"]
