from __future__ import annotations

from datetime import date
from typing import Any

from mining_rights_daily.agent.briefing import BriefingData
from mining_rights_daily.agent.intent import parse_intent
from mining_rights_daily.agent.protocol import Step


def load_briefing(state: dict[str, Any]) -> BriefingData:
    data = BriefingData(intent=parse_intent(str(state["query"]), date.fromisoformat(str(state["as_of"]))))
    data.news = state.get("news")
    data.news_error = state.get("news_error")
    data.articles = list(state.get("articles") or [])
    data.article_errors = list(state.get("article_errors") or [])
    data.resources = state.get("resources")
    data.resources_error = state.get("resources_error")
    data.price = state.get("price")
    data.price_error = state.get("price_error")
    data.trend = state.get("trend")
    data.trend_error = state.get("trend_error")
    data.steps = [_step_from(item) for item in state.get("steps") or []]
    return data


def dump_briefing(data: BriefingData, query: str, as_of: str) -> dict[str, Any]:
    return {
        "query": query,
        "as_of": as_of,
        "news": data.news,
        "news_error": data.news_error,
        "articles": data.articles,
        "article_errors": data.article_errors,
        "resources": data.resources,
        "resources_error": data.resources_error,
        "price": data.price,
        "price_error": data.price_error,
        "trend": data.trend,
        "trend_error": data.trend_error,
        "steps": [_step_to(step) for step in data.steps],
    }


def _step_to(step: Step) -> dict[str, Any]:
    return {
        "thought": step.thought,
        "server": step.server,
        "tool": step.tool,
        "arguments": step.arguments,
        "ok": step.ok,
        "summary": step.summary,
        "payload": step.payload,
    }


def _step_from(raw: dict[str, Any]) -> Step:
    return Step(
        thought=str(raw.get("thought") or ""),
        server=str(raw.get("server") or ""),
        tool=str(raw.get("tool") or ""),
        arguments=dict(raw.get("arguments") or {}),
        ok=bool(raw.get("ok")),
        summary=str(raw.get("summary") or ""),
        payload=raw.get("payload"),
    )
