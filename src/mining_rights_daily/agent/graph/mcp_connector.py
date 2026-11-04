from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

from mining_rights_daily.agent.graph.config import (
    tool_retry_attempts,
    tool_retry_base_delay,
    tool_timeout_seconds,
)
from mining_rights_daily.agent.graph.deepseek import DeepSeekClient
from mining_rights_daily.agent.graph.retry import current_budget, with_retry
from mining_rights_daily.agent.protocol import ToolBus, ToolCallError

_BUS: ContextVar[ToolBus | None] = ContextVar("mcp_bus", default=None)
_MODEL: ContextVar[DeepSeekClient | None] = ContextVar("deepseek_client", default=None)


class TimeoutBus:
    def __init__(
        self,
        inner: ToolBus,
        seconds: float,
        *,
        max_attempts: int | None = None,
        base_delay: float | None = None,
    ) -> None:
        self.inner = inner
        self.seconds = seconds
        self.max_attempts = tool_retry_attempts() if max_attempts is None else max_attempts
        self.base_delay = tool_retry_base_delay() if base_delay is None else base_delay

    async def call(self, server: str, tool: str, arguments: Mapping[str, Any]) -> Any:
        async def once() -> Any:
            try:
                return await asyncio.wait_for(
                    self.inner.call(server, tool, arguments),
                    self.seconds,
                )
            except TimeoutError as exc:
                raise ToolCallError(f"{server}.{tool} 超时") from exc

        return await with_retry(
            once,
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
            budget=current_budget(),
            label=f"{server}.{tool}",
        )


def bind_bus(bus: ToolBus) -> Token[ToolBus | None]:
    return _BUS.set(TimeoutBus(bus, tool_timeout_seconds()))


def reset_bus(token: Token[ToolBus | None]) -> None:
    _BUS.reset(token)


def current_bus() -> ToolBus:
    bus = _BUS.get()
    if bus is None:
        raise ToolCallError("MCP 连接未建立")
    return bus


def bind_model(client: DeepSeekClient | None) -> Token[DeepSeekClient | None]:
    return _MODEL.set(client)


def reset_model(token: Token[DeepSeekClient | None]) -> None:
    _MODEL.reset(token)


def current_model() -> DeepSeekClient | None:
    return _MODEL.get()

