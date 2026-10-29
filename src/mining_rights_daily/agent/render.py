from __future__ import annotations

import json
import re
from typing import Any

from mining_rights_daily.agent.briefing import BriefingData

_BARS = "▁▂▃▄▅▆▇█"
_SOURCE_LABELS = {
    "fixture": "离线样本",
    "rss": "RSS",
    "announcement": "公司公告",
    "web": "网页",
    "pdf": "PDF",
}
_DIRECTION = {"up": "上涨", "down": "下跌", "flat": "基本持平"}
_WATCH = (
    ("suspension", "正文出现 suspension，需要核对是否停产或停运。"),
    ("force majeure", "正文出现 force majeure，需要核对不可抗力的范围和期限。"),
    ("spill", "正文出现 spill，需要核对泄漏量和监管通报。"),
    ("offtake", "正文提到 offtake（承购）。精矿销价和氢氧化锂参考价不是同一个合约。"),
    ("heritage", "正文提到 heritage。西澳项目要单独看遗产调查和地面作业许可。"),
    ("water", "正文提到 water。选厂和采场会受取水和旱季条件影响。"),
)


def render_briefing(data: BriefingData) -> str:
    intent = data.intent
    lines = [
        f"# 矿权日报 · {intent.asset_label}",
        "",
        f"**日期：{_cn_date(intent.as_of)}**",
        "",
        f"- 简报日: {intent.as_of.isoformat()}",
        f"- 问题: {intent.raw_query}",
        "- 编排: 脚本化 ReAct。数字只来自 MCP 工具返回值，写稿步骤不另行估算储量或价格。",
        "",
        "## 新闻摘要",
        "",
        *_news_section(data),
        "",
        "## 储量数据",
        "",
        *_resource_section(data),
        "",
        "## 价格走势",
        "",
        *_price_section(data),
        "",
        "## 风险提示",
        "",
        *_risks(data),
        "",
        "## 引用",
        "",
        *_citations(data),
        "",
        "## 工具调用",
        "",
        *_trace(data),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _news_section(data: BriefingData) -> list[str]:
    if data.news_error:
        return [f"新闻工具失败: {data.news_error}"]
    if not data.news or not data.news.get("items"):
        return ["扩大到 800 天后仍然没有匹配新闻。"]
    window = data.news
    lines = [
        f"检索词 `{window.get('query')}`，窗口 {window.get('window_start')} 至 {window.get('as_of')}（{window.get('days')} 天）。"
    ]
    if window.get("days") != data.intent.news_days:
        lines.append(f"按问句本应看 {data.intent.news_days} 天；该窗口为空，所以使用了上面的扩大窗口。")
    if window.get("live_feed_errors"):
        lines.append("在线来源没有并入: " + "；".join(window["live_feed_errors"]))
    by_url = {article.get("url"): article for article in data.articles}
    for index, item in enumerate(window.get("items") or [], start=1):
        if index > 3:
            break
        article = by_url.get(item.get("url"))
        text = (article or {}).get("text") or item.get("snippet") or ""
        source_type = _SOURCE_LABELS.get(
            str(item.get("source_type") or ""),
            str(item.get("source_type") or "web"),
        )
        lines.extend(
            [
                "",
                f"### {index}. {item.get('title')}",
                "",
                text,
                "",
                f"- 来源: {item.get('source')}（{source_type}）",
                f"- 日期: {item.get('published_at') or '未知'}",
                f"- 链接: `{item.get('url')}`",
            ]
        )
    for error in data.article_errors:
        lines.append(f"- 正文读取失败: {error}")
    return lines


def _resource_section(data: BriefingData) -> list[str]:
    if data.intent.report_url is None:
        return ["报告目录里没有这个标的的 NI 43-101，本段没有储量数字。"]
    if data.resources_error:
        return [f"PDF 工具失败: {data.resources_error}"]
    report = data.resources or {}
    lines: list[str] = []
    if report.get("is_synthetic"):
        lines.append(
            "> 这是合成的演示报告，用来验证 PDF 解析。它不是矿业公司的正式披露，不能当作 Pilbara Minerals 的官方储量。"
        )
        lines.append("")
    lines.extend(
        [
            f"- 项目: {report.get('project') or '未识别'}",
            f"- 位置: {report.get('location') or '未识别'}",
            f"- 标准: {report.get('standard')}",
            f"- 生效日: {report.get('effective_date') or '未识别'}",
            f"- 文件: `{report.get('pdf_url')}`",
        ]
    )
    for warning in report.get("parse_warnings") or []:
        lines.append(f"- 解析提示: {warning}")
    rows = report.get("rows") or []
    for kind, title in (("resource", "资源量"), ("reserve", "储量")):
        selected = [row for row in rows if row.get("kind") == kind]
        lines.extend(["", f"### {title}", ""])
        if not selected:
            lines.append("没有识别到这一类。")
            continue
        lines.extend(
            [
                "| 类别 | 矿石量 (Mt) | 品位 | 金属量 |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in selected:
            grade = f"{_num(row.get('grade_pct'))} {row.get('grade_label') or ''}".strip()
            contained = "—"
            if row.get("contained_kt") is not None:
                contained = f"{_num(row.get('contained_kt'))} {row.get('contained_label') or ''}".strip()
            lines.append(f"| {row.get('category')} | {_num(row.get('tonnes_mt'))} | {grade} | {contained} |")
    return lines


def _price_section(data: BriefingData) -> list[str]:
    if data.intent.commodity is None:
        return ["问句里没有识别出商品，本段没有价格。"]
    lines: list[str] = []
    if data.price_error:
        lines.append(f"价格工具失败: {data.price_error}")
    elif data.price:
        quote = data.price
        lines.extend(
            [
                f"- 合约: {quote.get('contract')}",
                f"- 来源: `{quote.get('source')}`",
                f"- 请求日 {quote.get('requested_date')}，采用交易日 {quote.get('resolved_date')}: **{_num(quote.get('close'))} {quote.get('unit')}**",
            ]
        )
        if quote.get("day_change_pct") is not None:
            lines.append(f"- 较前一交易日: {_num(quote.get('day_change_pct'))}%")
        if quote.get("note"):
            lines.append(f"- 说明: {quote['note']}")
        lines.append(f"- 免责声明: {quote.get('disclaimer')}")
    if data.trend_error:
        lines.append(f"走势工具失败: {data.trend_error}")
    elif data.trend:
        trend = data.trend
        direction = _DIRECTION.get(str(trend.get("direction")), str(trend.get("direction")))
        change_pct = abs(float(trend.get("change_pct")))
        lines.extend(
            [
                "",
                (
                    f"最近 {trend.get('days')} 个交易日（{trend.get('start_date')} → {trend.get('end_date')}）"
                    f"从 {_num(trend.get('start'))} 到 {_num(trend.get('end'))} {trend.get('unit')}，"
                    f"{direction} {_num(change_pct)}%。"
                    f"区间高点 {_num(trend.get('high'))}，低点 {_num(trend.get('low'))}。"
                ),
                "",
                _sparkline([float(point["close"]) for point in trend.get("points") or []]),
                "",
                "| 日期 | 收盘 |",
                "| --- | ---: |",
            ]
        )
        for point in (trend.get("points") or [])[-5:]:
            lines.append(f"| {point.get('date')} | {_num(point.get('close'))} |")
        if trend.get("note"):
            lines.append("")
            lines.append(f"说明: {trend['note']}")
    return lines or ["没有价格数据。"]


def _risks(data: BriefingData) -> list[str]:
    risks: list[str] = []
    report = data.resources or {}
    rows = report.get("rows") or []
    if report.get("is_synthetic"):
        risks.append("储量段来自合成 PDF。在替换成 SEDAR+ 或公司正式技术报告之前，不能用这些吨位做投资判断。")
    inferred = _row(rows, "Inferred")
    indicated = _row(rows, "Indicated")
    if inferred and indicated:
        risks.append(
            f"Indicated {_num(indicated.get('tonnes_mt'))} Mt，Inferred {_num(inferred.get('tonnes_mt'))} Mt。"
            "NI 43-101 下 Inferred 的地质把握低于 Indicated，不能直接当成储量或开采计划。"
        )
    if any(row.get("kind") == "resource" for row in rows) and any(row.get("kind") == "reserve" for row in rows):
        risks.append("资源量和储量是两套分类。资源量含储量时，两张表不能相加。")
    if data.intent.report_url is None:
        risks.append("没有匹配的技术报告，储量风险无法从文件里核对。")
    if data.resources_error:
        risks.append(f"技术报告没有读成: {data.resources_error}")
    trend = data.trend or {}
    if trend.get("change_pct") is not None and float(trend["change_pct"]) <= -5:
        risks.append(
            f"参考价在最近 {trend.get('days')} 个交易日下跌 {_num(abs(float(trend['change_pct'])))}%。"
            "这会压收入预期，也可能触发承购条款重谈。"
        )
    elif trend.get("change_pct") is not None and float(trend["change_pct"]) >= 5:
        risks.append(
            f"参考价在最近 {trend.get('days')} 个交易日上涨 {_num(abs(float(trend['change_pct'])))}%。"
            "上涨会改善收入，但也可能让买方推迟锁量。"
        )
    if data.intent.commodity == "lithium":
        risks.append("价格序列是氢氧化锂参考价。Pilgangoora 销售的是辉石精矿，不能把这个收盘价当成精矿结算价。")
    if data.price and data.price.get("disclaimer"):
        risks.append("价格不是 LME 官方结算价，不能用来下单或做结算。")
    if data.price_error or data.trend_error:
        risks.append("价格工具有失败项，走势结论不完整。")
    blob = " ".join(str(article.get("text") or "") for article in data.articles)
    for _needle, message in watch_hits(blob):
        risks.append(message)
    if not risks:
        risks.append("这次工具结果里没有额外触发风险规则。数据范围和免责声明仍然有效。")
    return [f"{index}. {item}" for index, item in enumerate(risks, start=1)]


def _citations(data: BriefingData) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    headlines = {
        str(item.get("url") or ""): str(item.get("title") or "")
        for item in (data.news or {}).get("items") or []
    }
    for article in data.articles:
        url = str(article.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        title = headlines.get(url) or article.get("title")
        lines.append(f"{len(lines) + 1}. {title} — `{url}`")
    if data.resources and data.resources.get("pdf_url"):
        lines.append(f"{len(lines) + 1}. 技术报告 — `{data.resources['pdf_url']}`")
    if data.price and data.price.get("source"):
        lines.append(f"{len(lines) + 1}. 价格序列 — `{data.price['source']}`")
    return lines or ["没有可引用的来源。"]


def _trace(data: BriefingData) -> list[str]:
    if not data.steps:
        return ["没有工具调用。"]
    lines: list[str] = []
    for index, step in enumerate(data.steps, start=1):
        args = json.dumps(step.arguments, ensure_ascii=False)
        lines.append(f"{index}. {step.thought}")
        lines.append(f"   - 调用 `{step.server}.{step.tool}` `{args}`")
        lines.append(f"   - 结果: {step.summary}")
    return lines


def watch_hits(text: str) -> list[tuple[str, str]]:
    """Return watch rules whose keyword appears outside a negated sentence."""

    hits: list[tuple[str, str]] = []
    lowered = text.lower()
    sentences = re.split(r"[.!?]+", lowered)
    for needle, message in _WATCH:
        for sentence in sentences:
            if needle not in sentence:
                continue
            if re.search(r"\b(no|not|without|never)\b|n't", sentence):
                continue
            hits.append((needle, message))
            break
    return hits


def _row(rows: list[dict[str, Any]], category: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("category")).lower() == category.lower():
            return row
    return None


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    low = min(values)
    high = max(values)
    if high == low:
        return _BARS[0] * len(values)
    chars = []
    for value in values:
        index = round((value - low) / (high - low) * (len(_BARS) - 1))
        chars.append(_BARS[index])
    return "`" + "".join(chars) + "`"


def _cn_date(day: Any) -> str:
    weekdays = "一二三四五六日"
    return f"{day.year}年{day.month}月{day.day}日（星期{weekdays[day.weekday()]}）"


def _num(value: Any) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")
