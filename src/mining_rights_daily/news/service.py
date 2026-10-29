from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from pypdf import PdfReader

from mining_rights_daily.errors import DomainError
from mining_rights_daily.net import fetch_limited, iter_text_preview
from mining_rights_daily.paths import NEWS_PATH

MAX_DAYS = 800
LIVE_FEED = "https://www.mining.com/feed/"
RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; mining-rights-daily/0.1)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}
ASX_FEED = "https://asx.api.markitdigital.com/asx-research/1.0/companies/PLS/announcements?count=20"
ASX_FILE = "https://asx.api.markitdigital.com/asx-research/1.0/file/{key}?access_token=a"
_ASX_ZONE = ZoneInfo("Australia/Sydney")
_PLS_KEYWORDS = ["pilbara", "lithium", "spodumene", "pls"]
_TOKEN_MAP = (
    ("皮尔巴拉", "pilbara"),
    ("碳酸锂", "lithium"),
    ("锂矿", "lithium"),
    ("辉石", "spodumene"),
    ("锂", "lithium"),
)
_STOPWORDS = {"the", "and", "for", "about", "today", "news", "mine"}
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class SearchHit(BaseModel):
    title: str
    url: str
    source: str
    source_type: str
    published_at: str
    snippet: str


class SearchResult(BaseModel):
    query: str
    days: int
    as_of: str
    window_start: str
    items: list[SearchHit]
    live_enabled: bool
    live_feed_errors: list[str] = Field(default_factory=list)


class Article(BaseModel):
    title: str
    url: str
    source: str
    source_type: str
    published_at: str
    text: str


def search_news(
    query: str,
    days: int = 7,
    as_of: str | None = None,
    *,
    enable_live: bool | None = None,
    live_items: list[dict[str, str]] | None = None,
) -> SearchResult:
    tokens = _tokens(query)
    if not tokens:
        raise DomainError("查询里没有可检索的词")
    if days < 1 or days > MAX_DAYS:
        raise DomainError(f"days 必须在 1 到 {MAX_DAYS} 之间")
    clock = _parse_day(as_of) if as_of else date.today()
    window_start = clock - timedelta(days=days - 1)
    live = _live_enabled(enable_live)
    errors: list[str] = []
    rows = _load_articles()
    if live_items is not None:
        rows = [*rows, *live_items]
    elif live:
        extra, feed_errors = _fetch_live(clock)
        rows = [*rows, *extra]
        errors.extend(feed_errors)
    seen: set[str] = set()
    hits: list[SearchHit] = []
    for row in rows:
        published = _parse_day(str(row.get("published_at", "")))
        if published < window_start or published > clock:
            continue
        if not _matches(tokens, row):
            continue
        url = str(row["url"])
        if url in seen:
            continue
        seen.add(url)
        body = str(row.get("body") or row.get("snippet") or "")
        hits.append(
            SearchHit(
                title=str(row["title"]),
                url=url,
                source=str(row.get("source") or "unknown"),
                source_type=str(row.get("source_type") or "rss"),
                published_at=published.isoformat(),
                snippet=iter_text_preview(body, 180),
            )
        )
    hits.sort(key=lambda item: (item.published_at, "presentation" not in item.title.lower(), item.title), reverse=True)
    return SearchResult(
        query=query,
        days=days,
        as_of=clock.isoformat(),
        window_start=window_start.isoformat(),
        items=hits[:8],
        live_enabled=live,
        live_feed_errors=errors,
    )


def fetch_article(url: str) -> Article:
    if not url or not url.strip():
        raise DomainError("url 不能为空")
    target = url.strip()
    if target.startswith("fixture://"):
        for row in _load_articles():
            if row["url"] == target:
                return Article(
                    title=row["title"],
                    url=row["url"],
                    source=row["source"],
                    source_type=row["source_type"],
                    published_at=row["published_at"],
                    text=row["body"],
                )
        raise DomainError(f"语料里没有这篇文章: {target}")
    if not target.startswith(("http://", "https://")):
        raise DomainError("fetch_article 只接受 fixture://、http:// 或 https://")
    payload, _detail = fetch_limited(target, timeout=8, max_bytes=5_000_000)
    if payload.startswith(b"%PDF"):
        text = _pdf_to_text(payload)
        source_type = "announcement" if "asx.api.markitdigital.com" in target else "pdf"
        source = "ASX" if source_type == "announcement" else target
    else:
        text = _html_to_text(payload.decode("utf-8", errors="replace"))
        source_type = "web"
        source = target
    if not text:
        raise DomainError("页面没有可提取的正文")
    title = text.split(" ", 1)[0]
    return Article(
        title=title,
        url=target,
        source=source,
        source_type=source_type,
        published_at="",
        text=iter_text_preview(text, 1200 if source_type in {"announcement", "pdf"} else 8000),
    )


def _load_articles() -> list[dict[str, str]]:
    document = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
    return list(document["articles"])


def _tokens(query: str) -> list[str]:
    remaining = query.strip().lower()
    found: list[str] = []
    for raw, canon in _TOKEN_MAP:
        if raw in remaining:
            found.append(canon)
            remaining = remaining.replace(raw, " ")
    found.extend(re.findall(r"[a-z][a-z0-9_-]{2,}", remaining))
    unique: list[str] = []
    for token in found:
        if token in _STOPWORDS or token in unique:
            continue
        unique.append(token)
    return unique


def _matches(tokens: list[str], row: dict[str, str]) -> bool:
    haystack = " ".join(
        [
            str(row.get("title", "")),
            str(row.get("body", "")),
            str(row.get("snippet", "")),
            " ".join(row.get("keywords", [])),
        ]
    ).lower()
    return all(_token_in_haystack(token, haystack) for token in tokens)


def _token_in_haystack(token: str, haystack: str) -> bool:
    if token == "lithium":
        return "lithium" in haystack or "spodumene" in haystack
    if token == "spodumene":
        return "spodumene" in haystack or "lithium" in haystack
    return token in haystack


def _live_enabled(flag: bool | None) -> bool:
    if flag is not None:
        return flag
    return os.environ.get("NEWS_ENABLE_LIVE", "1") != "0"


def parse_asx_announcements(payload: bytes) -> list[dict[str, object]]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DomainError(f"ASX 公告不是合法 JSON: {exc}") from exc
    data = document.get("data") if isinstance(document, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise DomainError("ASX 公告缺少 data.items")
    issuer = str(data.get("displayName") or "PLS")
    symbol = str(data.get("symbol") or "PLS")
    rows: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or "").strip()
        key = str(item.get("documentKey") or "").strip()
        published = _parse_asx_instant(str(item.get("date") or ""))
        if not headline or not key or published is None:
            continue
        kind = str(item.get("announcementType") or "ANNOUNCEMENT")
        flag = "价格敏感" if item.get("isPriceSensitive") else "非价格敏感"
        rows.append(
            {
                "title": headline,
                "url": ASX_FILE.format(key=key),
                "source": "ASX",
                "source_type": "announcement",
                "published_at": published.isoformat(),
                "body": (
                    f"{issuer}（ASX:{symbol}）{kind}。{headline}。{flag}。"
                    "这是交易所公告原文链接，不是新闻转载。"
                ),
                "keywords": [*_PLS_KEYWORDS],
            }
        )
    return rows


def _fetch_live(clock: date) -> tuple[list[dict[str, object]], list[str]]:
    items: list[dict[str, object]] = []
    errors: list[str] = []
    loaders = (("mining.com RSS", _fetch_rss), ("ASX:PLS 公告", _fetch_asx))
    with ThreadPoolExecutor(max_workers=len(loaders)) as pool:
        futures = {pool.submit(loader, clock): label for label, loader in loaders}
        for future, label in futures.items():
            try:
                items.extend(future.result())
            except DomainError as exc:
                errors.append(f"{label}: {exc}")
    return items, errors


def _fetch_rss(clock: date) -> list[dict[str, object]]:
    payload, _detail = fetch_limited(LIVE_FEED, timeout=10, max_bytes=2_000_000, headers=RSS_HEADERS)
    items: list[dict[str, str]] = []
    for item in _parse_rss(payload.decode("utf-8", errors="replace")):
        published = item.get("published_at") or clock.isoformat()
        items.append(
            {
                "title": item["title"],
                "url": item["url"],
                "source": "mining.com",
                "source_type": "rss",
                "published_at": published,
                "body": item.get("body") or item["title"],
                "keywords": [],
            }
        )
    return items


def _fetch_asx(_clock: date) -> list[dict[str, object]]:
    payload, _detail = fetch_limited(ASX_FEED, timeout=15, max_bytes=2_000_000)
    return parse_asx_announcements(payload)


def _parse_rss(xml_text: str) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise DomainError(f"RSS 不是合法 XML: {exc}") from exc
    parsed: list[dict[str, str]] = []
    for node in root.iter():
        if _local(node.tag) != "item":
            continue
        title = _child_text(node, "title")
        link = _child_text(node, "link")
        if not title or not link:
            continue
        published = _parse_day_optional(_child_text(node, "pubDate") or _child_text(node, "date"))
        parsed.append(
            {
                "title": _WS.sub(" ", title).strip(),
                "url": link.strip(),
                "body": _html_to_text(_child_text(node, "description")),
                "published_at": published.isoformat() if published else "",
            }
        )
    return parsed


def _child_text(node: ElementTree.Element, name: str) -> str:
    for child in list(node):
        if _local(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_asx_instant(value: str) -> date | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        instant = datetime.fromisoformat(raw)
    except ValueError:
        return _parse_day_optional(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(_ASX_ZONE).date()


def _pdf_to_text(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload))
    except Exception as exc:
        raise DomainError(f"PDF 无法读取: {exc}") from exc
    pages: list[str] = []
    for page in reader.pages[:4]:
        pages.append(page.extract_text() or "")
    return _strip_asx_letterhead(_WS.sub(" ", " ".join(pages)).strip())


def _strip_asx_letterhead(text: str) -> str:
    marker = "ASX Announcement"
    index = text.find(marker)
    if index < 0:
        return text
    rest = text[index + len(marker) :].strip()
    rest = re.sub(r"^ASX:\s*[A-Z0-9]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+", "", rest)
    return rest or text


def _html_to_text(value: str) -> str:
    without_blocks = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    return _WS.sub(" ", _TAG.sub(" ", without_blocks)).strip()


def _parse_day(value: str) -> date:
    parsed = _parse_day_optional(value)
    if parsed is None:
        raise DomainError(f"无法解析日期: {value}")
    return parsed


def _parse_day_optional(value: str) -> date | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
