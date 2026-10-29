from __future__ import annotations

import logging
import sys
from datetime import date
from typing import Any

from mining_rights_daily.agent.briefing import BriefingData
from mining_rights_daily.agent.intent import parse_intent
from mining_rights_daily.agent.protocol import Step, ToolBus, ToolCallError
from mining_rights_daily.agent.render import render_briefing
from mining_rights_daily.logging import configure_logging


async def generate_briefing(query: str, bus: ToolBus, as_of: date) -> str:
    configure_logging("mining-daily-agent")
    data = await collect(query, bus, as_of)
    return render_briefing(data)


async def collect(query: str, bus: ToolBus, as_of: date) -> BriefingData:
    intent = parse_intent(query, as_of)
    data = BriefingData(intent=intent)
    await _news(data, bus)
    await _resources(data, bus)
    await _prices(data, bus)
    return data


async def _news(data: BriefingData, bus: ToolBus) -> None:
    intent = data.intent
    for index, window in enumerate(_windows(intent.news_days)):
        if index == 0 and window == 1:
            thought = f"检索 {intent.news_query} 在 {intent.as_of.isoformat()} 当天的新闻"
        elif index == 0:
            thought = (
                f"检索 {intent.news_query}，截止 {intent.as_of.isoformat()}，共 {window} 天（含当天）"
            )
        else:
            thought = f"当天没有新闻，把窗口扩大到截止日往前共 {window} 天"
        payload, error = await _call(
            data,
            bus,
            thought,
            "mining-news",
            "search",
            {"query": intent.news_query, "days": window, "as_of": intent.as_of.isoformat()},
            _search_summary,
        )
        if error:
            data.news_error = error
            return
        data.news = payload
        items = payload.get("items") or []
        if items:
            break
    if not data.news or not data.news.get("items"):
        return
    for item in data.news["items"][:3]:
        payload, error = await _call(
            data,
            bus,
            f"读取新闻正文: {item.get('title')}",
            "mining-news",
            "fetch_article",
            {"url": item["url"]},
            lambda body: f"正文 {len(str(body.get('text', '')))} 字",
        )
        if error:
            data.article_errors.append(f"{item.get('url')}: {error}")
            continue
        data.articles.append(payload)


async def _resources(data: BriefingData, bus: ToolBus) -> None:
    url = data.intent.report_url
    if not url:
        data.steps.append(
            Step(
                thought="报告目录里没有和该标的匹配的 NI 43-101",
                server="mineral-pdf",
                tool="extract_resources",
                arguments={},
                ok=True,
                summary="未调用",
            )
        )
        _log(data.steps[-1])
        return
    payload, error = await _call(
        data,
        bus,
        f"解析技术报告 {url}",
        "mineral-pdf",
        "extract_resources",
        {"pdf_url": url},
        lambda body: f"识别到 {len(body.get('rows') or [])} 行资源或储量",
    )
    data.resources = payload
    data.resources_error = error


async def _prices(data: BriefingData, bus: ToolBus) -> None:
    commodity = data.intent.commodity
    if not commodity:
        data.steps.append(
            Step(
                thought="问句里没有识别出商品，跳过价格工具",
                server="lme-price",
                tool="get_price",
                arguments={},
                ok=True,
                summary="未调用",
            )
        )
        _log(data.steps[-1])
        return
    on_date = data.intent.as_of.isoformat()
    payload, error = await _call(
        data,
        bus,
        f"读取 {commodity} 在 {on_date} 的参考价",
        "lme-price",
        "get_price",
        {"commodity": commodity, "date": on_date},
        lambda body: f"{body.get('close')} {body.get('unit')} @ {body.get('resolved_date')}",
    )
    data.price = payload
    data.price_error = error
    payload, error = await _call(
        data,
        bus,
        f"读取 {commodity} 最近 {data.intent.trend_days} 个交易日走势",
        "lme-price",
        "get_trend",
        {"commodity": commodity, "days": data.intent.trend_days},
        lambda body: f"{body.get('direction')} {body.get('change_pct')}%",
    )
    data.trend = payload
    data.trend_error = error


async def _call(
    data: BriefingData,
    bus: ToolBus,
    thought: str,
    server: str,
    tool: str,
    arguments: dict[str, Any],
    summarize,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = await bus.call(server, tool, arguments)
    except (ToolCallError, KeyError, TypeError) as exc:
        step = Step(thought, server, tool, arguments, False, str(exc))
        data.steps.append(step)
        _log(step)
        return None, str(exc)
    if not isinstance(payload, dict):
        message = "工具返回的不是对象"
        step = Step(thought, server, tool, arguments, False, message, payload)
        data.steps.append(step)
        _log(step)
        return None, message
    step = Step(thought, server, tool, arguments, True, summarize(payload), payload)
    data.steps.append(step)
    _log(step)
    return payload, None


def _search_summary(payload: dict[str, Any]) -> str:
    items = payload.get("items") or []
    return f"命中 {len(items)} 篇，窗口 {payload.get('window_start')} 至 {payload.get('as_of')}"


def _windows(requested: int) -> list[int]:
    windows = [requested]
    for extra in (14, 120, 800):
        if extra > requested:
            windows.append(extra)
    return windows


def _log(step: Step) -> None:
    status = "ok" if step.ok else "error"
    logging.getLogger("mining_rights_daily.agent").info(
        "%s %s.%s %s",
        status,
        step.server,
        step.tool,
        step.summary,
        extra={"server": step.server, "tool": step.tool, "ok": step.ok},
    )
    print(
        f"[react] {status} {step.server}.{step.tool} — {step.thought} — {step.summary}",
        file=sys.stderr,
    )
