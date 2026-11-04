from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from mining_rights_daily.agent.graph.config import request_budget_seconds
from mining_rights_daily.agent.graph.deepseek import DeepSeekClient
from mining_rights_daily.agent.graph.main_graph import compile_main
from mining_rights_daily.agent.graph.mcp_connector import (
    bind_bus,
    bind_model,
    reset_bus,
    reset_model,
)
from mining_rights_daily.agent.graph.retry import RequestBudget, bind_budget, reset_budget
from mining_rights_daily.agent.protocol import ToolBus


async def run_turn(
    query: str,
    as_of: date,
    bus: ToolBus,
    checkpoint_path: Path,
    thread_id: str,
    deepseek: Any = None,
) -> str:
    chunks = [
        item["markdown"]
        async for item in stream_turn(query, as_of, bus, checkpoint_path, thread_id, deepseek)
        if item["event"] == "report"
    ]
    return chunks[-1] if chunks else ""


async def stream_turn(
    query: str,
    as_of: date,
    bus: ToolBus,
    checkpoint_path: Path,
    thread_id: str,
    deepseek: Any = None,
) -> AsyncIterator[dict[str, str]]:
    path = Path(checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    client = DeepSeekClient.from_env() if deepseek is None else deepseek
    deadline = asyncio.get_running_loop().time() + request_budget_seconds()
    bus_token = bind_bus(bus)
    model_token = bind_model(client)
    budget_token = bind_budget(RequestBudget(deadline=deadline))
    final = ""
    try:
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            graph = compile_main(saver)
            config = {"configurable": {"thread_id": thread_id}}
            payload = {"query": query, "as_of": as_of.isoformat()}
            async for update in graph.astream(payload, config, stream_mode="updates"):
                for name, node_payload in update.items():
                    yield {"event": "node", "node": str(name)}
                    chosen = _answer(node_payload)
                    if chosen.strip():
                        final = chosen
    finally:
        reset_budget(budget_token)
        reset_bus(bus_token)
        reset_model(model_token)
    if final and not final.endswith("\n"):
        final += "\n"
    yield {"event": "report", "markdown": final}


def _answer(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    single = str(payload.get("single_result") or "")
    report = str(payload.get("report") or "")
    if single.strip():
        return single
    return report
