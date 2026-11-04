from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

from mining_rights_daily.agent.graph.config import tool_timeout_seconds
from mining_rights_daily.agent.graph.deepseek import DeepSeekClient
from mining_rights_daily.agent.protocol import ToolBus, ToolCallError

_BUS: ContextVar[ToolBus | None] = ContextVar("mcp_bus", default=None)
_MODEL: ContextVar[DeepSeekClient | None] = ContextVar("deepseek_client", default=None)


class TimeoutBus:
    def __init__(self, inner: ToolBus, seconds: float) -> None:
        self.inner = inner
        self.seconds = seconds

    async def call(self, server: str, tool: str, arguments: Mapping[str, Any]) -> Any:
        try:
            return await asyncio.wait_for(
                self.inner.call(server, tool, arguments),
                self.seconds,
            )
        except TimeoutError as exc:
            raise ToolCallError(f"{server}.{tool} 超时") from exc


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
