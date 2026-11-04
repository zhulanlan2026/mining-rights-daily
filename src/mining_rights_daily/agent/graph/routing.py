from __future__ import annotations

import json
from datetime import date

from mining_rights_daily.agent.graph.deepseek import DeepSeekError, intent_system_prompt
from mining_rights_daily.agent.graph.mcp_connector import current_model

_FOLLOW = ("上一轮", "上一次", "刚才")
_DAILY = ("简报", "日报", "briefing")
_TREND = ("走势", "趋势", "trend")
_NEWS = ("新闻", "公告", "news")
_PDF = ("储量", "资源量", "43-101")
_PRICE = ("价格", "锂价", "铜价", "镍价", "金价", "报价", "多少钱", "行情", "price")
_ALLOWED = {
    "query_news",
    "query_pdf",
    "query_price",
    "query_trend",
    "generate_daily_report",
    "clarify",
    "follow_up",
}


def classify_rules(query: str, *, has_history: bool) -> str:
    text = query.strip().lower()
    if _hit(text, _FOLLOW):
        return "follow_up" if has_history else "clarify"
    if _hit(text, _DAILY):
        return "generate_daily_report"
    if _hit(text, _TREND):
        return "query_trend"
    if _hit(text, _NEWS):
        return "query_news"
    if _hit(text, _PDF):
        return "query_pdf"
    if _hit(text, _PRICE):
        return "query_price"
    return "clarify"


async def resolve_intent(query: str, as_of: date, messages: list[dict[str, str]]) -> str:
    del as_of
    has_history = any(item.get("role") == "assistant" and item.get("content") for item in messages)
    ruled = classify_rules(query, has_history=has_history)
    if ruled != "clarify":
        return ruled
    client = current_model()
    if client is None:
        return ruled
    try:
        raw = await client.complete(intent_system_prompt(), query.strip())
    except (DeepSeekError, TimeoutError, OSError):
        return ruled
    parsed = _parse_intent(raw)
    if parsed is None:
        return ruled
    if parsed == "follow_up" and not has_history:
        return "clarify"
    return parsed


def _parse_intent(raw: str) -> str | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    intent = str(payload.get("intent") or "")
    if intent not in _ALLOWED:
        return None
    return intent


def _hit(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)
