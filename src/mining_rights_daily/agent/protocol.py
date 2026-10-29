from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class ToolCallError(Exception):
    """A tool returned an MCP error or the session failed."""


class ToolBus(Protocol):
    async def call(self, server: str, tool: str, arguments: Mapping[str, Any]) -> Any:
        """Call one tool and return its structured payload."""


@dataclass
class Step:
    thought: str
    server: str
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    payload: Any = None


def unwrap_tool_result(result: Any) -> Any:
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        raise ToolCallError(_text(result) or "工具返回错误")
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        if set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    raw = _text(result)
    if raw.startswith("{") or raw.startswith("["):
        return json.loads(raw)
    if raw:
        return {"text": raw}
    raise ToolCallError("工具没有返回内容")


def _text(result: Any) -> str:
    blocks = getattr(result, "content", None) or []
    parts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()
