from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from mining_rights_daily.agent.graph.retry import RequestBudget, is_retryable, with_retry
from mining_rights_daily.agent.protocol import ToolCallError


def test_timeouts_and_rate_limits_are_retryable() -> None:
    assert is_retryable(ToolCallError("mining-news.fetch_article 超时"))
    assert is_retryable(ToolCallError("调用失败: ConnectError"))
    assert is_retryable(ToolCallError("DeepSeek 请求失败: HTTP 429"))
    assert is_retryable(ToolCallError("DeepSeek 请求失败: HTTP 503"))
    assert is_retryable(TimeoutError())


def test_validation_errors_are_not_retryable() -> None:
    assert not is_retryable(ToolCallError("MCP 连接未建立"))
    assert not is_retryable(ToolCallError("不支持的商品 'foo'"))
    assert not is_retryable(ToolCallError("DeepSeek 请求失败: HTTP 401"))
    assert not is_retryable(ToolCallError("url 不能为空"))
    assert not is_retryable(ValueError("bad"))


def test_with_retry_retries_then_succeeds() -> None:
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ToolCallError("mining-news.search 超时")
        return "ok"

    assert asyncio.run(with_retry(flaky, max_attempts=3, base_delay=0.01)) == "ok"
    assert attempts == 3


def test_with_retry_does_not_retry_validation_errors() -> None:
    attempts = 0

    async def bad() -> str:
        nonlocal attempts
        attempts += 1
        raise ToolCallError("url 不能为空")

    with pytest.raises(ToolCallError, match="url"):
        asyncio.run(with_retry(bad, max_attempts=3, base_delay=0.01))
    assert attempts == 1


def test_with_retry_stops_when_request_budget_is_exhausted() -> None:
    attempts = 0

    async def scenario() -> None:
        nonlocal attempts
        budget = RequestBudget(deadline=asyncio.get_running_loop().time() + 0.05)

        async def always_timeout() -> str:
            nonlocal attempts
            attempts += 1
            await asyncio.sleep(0.03)
            raise ToolCallError("lme-price.get_price 超时")

        with pytest.raises(ToolCallError, match="超时|预算"):
            await with_retry(
                always_timeout,
                max_attempts=5,
                base_delay=0.01,
                budget=budget,
            )

    asyncio.run(scenario())
    assert attempts < 5


def test_timeout_bus_retries_retryable_tool_errors() -> None:
    from mining_rights_daily.agent.graph.mcp_connector import TimeoutBus

    class FlakyBus:
        def __init__(self) -> None:
            self.calls = 0

        async def call(self, server: str, tool: str, arguments: Mapping[str, Any]) -> Any:
            self.calls += 1
            if self.calls < 3:
                raise ToolCallError(f"{server}.{tool} 调用失败: ConnectError")
            return {"ok": True}

    async def scenario() -> None:
        inner = FlakyBus()
        bus = TimeoutBus(inner, seconds=5)
        assert await bus.call("mining-news", "search", {"query": "lithium"}) == {"ok": True}
        assert inner.calls == 3

    asyncio.run(scenario())
