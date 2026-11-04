from __future__ import annotations

import sys
from datetime import date
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from mining_rights_daily.agent.graph.routing import resolve_intent
from mining_rights_daily.agent.graph.sub_graph_factory import build_daily_subgraph, run_single

_daily = None


class MainState(TypedDict, total=False):
    query: str
    as_of: str
    intent: str
    params: dict[str, Any]
    report: str
    single_result: str
    messages: Annotated[list[dict[str, str]], add]


def compile_main(checkpointer: Any) -> CompiledStateGraph:
    graph = StateGraph(MainState)
    graph.add_node("intent", intent_node)
    graph.add_node("daily", daily_node)
    graph.add_node("single", single_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("follow_up", follow_up_node)
    graph.add_edge(START, "intent")
    graph.add_conditional_edges(
        "intent",
        route,
        ["daily", "single", "clarify", "follow_up"],
    )
    graph.add_edge("daily", END)
    graph.add_edge("single", END)
    graph.add_edge("clarify", END)
    graph.add_edge("follow_up", END)
    return graph.compile(checkpointer=checkpointer)


async def intent_node(state: MainState) -> dict[str, Any]:
    query = str(state.get("query") or "")
    as_of = date.fromisoformat(str(state["as_of"]))
    messages = list(state.get("messages") or [])
    kind = await resolve_intent(query, as_of, messages)
    print(f"[graph] intent={kind}", file=sys.stderr)
    return {
        "intent": kind,
        "params": {"query": query, "as_of": state.get("as_of")},
        "messages": [{"role": "user", "content": query}],
    }


def route(state: MainState) -> str:
    kind = state.get("intent") or "clarify"
    if kind == "generate_daily_report":
        return "daily"
    if kind in {"query_news", "query_pdf", "query_price", "query_trend"}:
        return "single"
    if kind == "follow_up":
        return "follow_up"
    return "clarify"


async def daily_node(state: MainState) -> dict[str, Any]:
    global _daily
    if _daily is None:
        _daily = build_daily_subgraph()
    try:
        out = await _daily.ainvoke({"query": state.get("query"), "as_of": state.get("as_of")})
        report = str(out.get("markdown_report") or "未获取到数据。\n")
    except Exception as exc:
        report = f"未获取到数据。日报子图失败: {exc}\n"
    return {"report": report, "single_result": "", "messages": [{"role": "assistant", "content": report}]}


async def single_node(state: MainState) -> dict[str, Any]:
    text = await run_single(
        str(state.get("intent") or "clarify"),
        str(state.get("query") or ""),
        date.fromisoformat(str(state["as_of"])),
    )
    return {"report": "", "single_result": text, "messages": [{"role": "assistant", "content": text}]}


async def clarify_node(state: MainState) -> dict[str, Any]:
    del state
    text = "请说明要查的内容。可以生成日报，或单独查新闻、储量、价格、走势。\n例如：生成 Pilbara 锂矿今日简报。\n"
    return {"report": "", "single_result": text, "messages": [{"role": "assistant", "content": text}]}


async def follow_up_node(state: MainState) -> dict[str, Any]:
    prior = [
        str(item.get("content") or "")
        for item in state.get("messages") or []
        if item.get("role") == "assistant" and item.get("content")
    ]
    if not prior:
        text = "没有上一轮结果。请先要求生成一份日报。\n"
    else:
        text = "上一轮结果如下：\n\n" + prior[-1]
        if not text.endswith("\n"):
            text += "\n"
    return {"report": "", "single_result": text, "messages": [{"role": "assistant", "content": text}]}
