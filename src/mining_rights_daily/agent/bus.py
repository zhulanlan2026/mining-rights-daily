from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client, StdioServerParameters

from mining_rights_daily.agent.protocol import ToolCallError, unwrap_tool_result

SERVER_MODULES = {
    "mining-news": "mining_rights_daily.servers.news",
    "mineral-pdf": "mining_rights_daily.servers.pdf",
    "lme-price": "mining_rights_daily.servers.price",
}

DEFAULT_HTTP_URLS = {
    "mining-news": "http://127.0.0.1:8001/mcp",
    "mineral-pdf": "http://127.0.0.1:8002/mcp",
    "lme-price": "http://127.0.0.1:8003/mcp",
}

# Longer than ARTICLE_FETCH_TOTAL_SECONDS so a slow PDF returns from the server
# before the client cancels the tool call.
TOOL_CALL_TIMEOUT_SECONDS = 120


class McpToolBus:
    def __init__(self, clients: dict[str, Client]) -> None:
        self._clients = clients

    async def call(self, server: str, tool: str, arguments: Mapping[str, Any]) -> Any:
        client = self._clients[server]
        try:
            result = await client.call_tool(tool, dict(arguments))
        except Exception as exc:
            raise ToolCallError(f"{server}.{tool} 调用失败: {exc}") from exc
        return unwrap_tool_result(result)


@asynccontextmanager
async def open_bus(transport: str, urls: dict[str, str] | None = None) -> AsyncIterator[McpToolBus]:
    opened: list[Client] = []
    try:
        if transport == "stdio":
            targets = [
                StdioServerParameters(command=sys.executable, args=["-m", module], env=_child_env())
                for module in SERVER_MODULES.values()
            ]
            retries = 1
        elif transport == "http":
            resolved = dict(DEFAULT_HTTP_URLS)
            if urls:
                resolved.update(urls)
            targets = [resolved[name] for name in SERVER_MODULES]
            retries = 20
        else:
            raise ToolCallError(f"未知传输: {transport}")
        for target in targets:
            opened.append(await _enter(target, retries=retries))
        clients = dict(zip(SERVER_MODULES, opened, strict=True))
        yield McpToolBus(clients)
    finally:
        for client in reversed(opened):
            await client.__aexit__(None, None, None)


async def _enter(target: Any, retries: int) -> Client:
    last: Exception | None = None
    for attempt in range(retries):
        client = Client(target, read_timeout_seconds=TOOL_CALL_TIMEOUT_SECONDS)
        try:
            await client.__aenter__()
        except Exception as exc:
            last = exc
            if attempt + 1 == retries:
                break
            await asyncio.sleep(0.5)
            continue
        return client
    raise ToolCallError(f"连接 MCP server 失败: {last}")


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MCP_TRANSPORT"] = "stdio"
    return env
