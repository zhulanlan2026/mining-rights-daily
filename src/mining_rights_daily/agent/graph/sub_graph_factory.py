from __future__ import annotations

from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from mining_rights_daily.agent.briefing import BriefingData
from mining_rights_daily.agent.graph.deepseek import (
    DeepSeekError,
    judgment_system_prompt,
    unsupported_numbers,
)
from mining_rights_daily.agent.graph.mcp_connector import current_bus, current_model
from mining_rights_daily.agent.graph.skill import required_headings
from mining_rights_daily.agent.graph.state import dump_briefing, load_briefing
from mining_rights_daily.agent.orchestrator import _call, _news, _prices, _resources
from mining_rights_daily.agent.render import render_briefing


class DailyState(TypedDict, total=False):
    query: str
    as_of: str
    news: dict[str, Any] | None
    news_error: str | None
    articles: list[dict[str, Any]]
    article_errors: list[str]
    resources: dict[str, Any] | None
    resources_error: str | None
    price: dict[str, Any] | None
    price_error: str | None
    trend: dict[str, Any] | None
    trend_error: str | None
    steps: list[dict[str, Any]]
    markdown_report: str


def build_daily_subgraph():
    graph = StateGraph(DailyState)
    graph.add_node("fetch_news", fetch_news)
    graph.add_node("fetch_pdf", fetch_pdf)
    graph.add_node("fetch_price", fetch_price)
    graph.add_node("summary_node", summary_node)
    graph.add_edge(START, "fetch_news")
    graph.add_edge("fetch_news", "fetch_pdf")
    graph.add_edge("fetch_pdf", "fetch_price")
    graph.add_edge("fetch_price", "summary_node")
    graph.add_edge("summary_node", END)
    return graph.compile()


async def fetch_news(state: DailyState) -> DailyState:
    return await _stage(state, "news")


async def fetch_pdf(state: DailyState) -> DailyState:
    return await _stage(state, "pdf")


async def fetch_price(state: DailyState) -> DailyState:
    return await _stage(state, "price")


async def summary_node(state: DailyState) -> DailyState:
    data = load_briefing(state)
    markdown = ensure_headings(render_briefing(data))
    markdown = await _with_judgment(markdown)
    dumped = dump_briefing(data, str(state["query"]), str(state["as_of"]))
    dumped["markdown_report"] = markdown
    return dumped


async def run_single(kind: str, query: str, as_of: date) -> str:
    data = load_briefing({"query": query, "as_of": as_of.isoformat()})
    bus = current_bus()
    if kind == "query_news":
        await _guard(data, lambda: _news(data, bus), "news_error")
        return _news_answer(data)
    if kind == "query_pdf":
        await _guard(data, lambda: _resources(data, bus), "resources_error")
        return _pdf_answer(data)
    if kind == "query_price":
        if data.intent.commodity is None:
            return "未获取到数据。问句里没有识别出商品。\n"
        await _guard(
            data,
            lambda: _one_price(data, "get_price", "读取参考价"),
            "price_error",
        )
        return _price_answer(data)
    if kind == "query_trend":
        if data.intent.commodity is None:
            return "未获取到数据。问句里没有识别出商品。\n"
        await _guard(
            data,
            lambda: _one_price(data, "get_trend", "读取走势"),
            "trend_error",
        )
        return _trend_answer(data)
    return "未获取到数据。\n"


async def _stage(state: DailyState, kind: str) -> DailyState:
    data = load_briefing(state)
    if kind == "news":
        await _guard(data, lambda: _news(data, current_bus()), "news_error")
    elif kind == "pdf":
        await _guard(data, lambda: _resources(data, current_bus()), "resources_error")
    else:
        await _guard(data, lambda: _prices(data, current_bus()), "price_error")
    return dump_briefing(data, str(state["query"]), str(state["as_of"]))


async def _guard(data: BriefingData, call, field: str) -> None:
    try:
        await call()
    except Exception as exc:
        if not getattr(data, field):
            setattr(data, field, str(exc))


async def _one_price(data: BriefingData, tool: str, thought: str) -> None:
    commodity = data.intent.commodity or ""
    if tool == "get_price":
        arguments = {"commodity": commodity, "date": data.intent.as_of.isoformat()}
        payload, error = await _call(
            data,
            current_bus(),
            thought,
            "lme-price",
            tool,
            arguments,
            lambda body: f"{body.get('close')} {body.get('unit')}",
        )
        data.price = payload
        data.price_error = error
        return
    arguments = {"commodity": commodity, "days": data.intent.trend_days}
    payload, error = await _call(
        data,
        current_bus(),
        thought,
        "lme-price",
        tool,
        arguments,
        lambda body: f"{body.get('direction')} {body.get('change_pct')}%",
    )
    data.trend = payload
    data.trend_error = error


def ensure_headings(markdown: str) -> str:
    for heading in required_headings():
        if heading in markdown:
            continue
        block = f"{heading}\n\n未获取到数据。\n\n"
        if "## 引用" in markdown:
            markdown = markdown.replace("## 引用", block + "## 引用", 1)
        else:
            markdown = markdown.rstrip() + "\n\n" + block
    return markdown


async def _with_judgment(markdown: str) -> str:
    client = current_model()
    if client is None:
        return markdown
    try:
        draft = await client.complete(judgment_system_prompt(), markdown)
    except (DeepSeekError, TimeoutError, OSError):
        return attach_judgment(markdown, "未获取到数据。DeepSeek 没有返回研判。")
    text = draft.strip()
    if text.startswith("##"):
        text = text.split("\n", 1)[-1].strip()
    bad = unsupported_numbers(text, markdown)
    if not text or bad:
        return attach_judgment(markdown, "未获取到数据。研判出现了工具结果里没有的数字，已丢弃。")
    model = getattr(getattr(client, "config", None), "model", None)
    if model:
        text = f"{text}\n\n- 模型: DeepSeek `{model}`"
    return attach_judgment(markdown, text)


def attach_judgment(markdown: str, judgment: str) -> str:
    block = f"## 简要研判\n\n{judgment.strip()}\n\n"
    needle = "## 引用\n"
    if needle in markdown:
        return markdown.replace(needle, block + needle, 1)
    return markdown.rstrip() + "\n\n" + block


def _news_answer(data: BriefingData) -> str:
    if data.news_error:
        return f"未获取到数据。{data.news_error}\n"
    items = (data.news or {}).get("items") or []
    if not items:
        return "未获取到数据。没有匹配的新闻。\n"
    lines = ["# 新闻", ""]
    by_url = {article.get("url"): article for article in data.articles}
    for item in items[:3]:
        article = by_url.get(item.get("url")) or {}
        text = article.get("text") or item.get("snippet") or ""
        lines.extend(
            [
                f"## {item.get('title')}",
                "",
                str(text),
                "",
                f"- 链接: `{item.get('url')}`",
                "",
            ]
        )
    for error in data.article_errors:
        lines.append(f"- 正文读取失败: {error}")
    return "\n".join(lines).rstrip() + "\n"


def _pdf_answer(data: BriefingData) -> str:
    if data.intent.report_url is None:
        return "未获取到数据。报告目录里没有这个标的的 NI 43-101。\n"
    if data.resources_error or not data.resources:
        detail = data.resources_error or "PDF 工具没有返回内容"
        return f"未获取到数据。{detail}\n"
    report = data.resources
    lines = ["# 储量", ""]
    if report.get("is_synthetic"):
        lines.append("这是合成的演示报告，不是矿业公司的正式披露。")
        lines.append("")
    lines.extend(
        [
            f"- 项目: {report.get('project') or '未识别'}",
            f"- 文件: `{report.get('pdf_url')}`",
            "",
        ]
    )
    return "\n".join(lines)


def _price_answer(data: BriefingData) -> str:
    if data.price_error or not data.price:
        detail = data.price_error or "价格工具没有返回内容"
        return f"未获取到数据。{detail}\n"
    quote = data.price
    lines = [
        f"# {data.intent.asset_label}参考价",
        "",
        (
            f"- 请求日 {quote.get('requested_date')}，采用交易日 {quote.get('resolved_date')}: "
            f"{quote.get('close')} {quote.get('unit')}"
        ),
        f"- 来源: `{quote.get('source')}`",
        f"- 免责声明: {quote.get('disclaimer')}",
        "",
    ]
    return "\n".join(lines)


def _trend_answer(data: BriefingData) -> str:
    if data.trend_error or not data.trend:
        detail = data.trend_error or "走势工具没有返回内容"
        return f"未获取到数据。{detail}\n"
    trend = data.trend
    lines = [
        f"# {data.intent.asset_label}走势",
        "",
        (
            f"- 最近 {trend.get('days')} 个交易日 {trend.get('direction')} "
            f"{trend.get('change_pct')}%（{trend.get('start')} → {trend.get('end')} {trend.get('unit')}）"
        ),
        f"- 免责声明: {trend.get('disclaimer') or '参考序列，不是 LME 结算价。'}",
        "",
    ]
    return "\n".join(lines)
