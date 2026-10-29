from __future__ import annotations

from datetime import date

import pytest

from mining_rights_daily.agent.briefing import BriefingData
from mining_rights_daily.agent.intent import parse_intent
from mining_rights_daily.agent.render import render_briefing
from mining_rights_daily.errors import DomainError
from mining_rights_daily.net import assert_public_http
from mining_rights_daily.news.service import (
    _strip_asx_letterhead,
    fetch_article,
    parse_asx_announcements,
    search_news,
)
from mining_rights_daily.paths import SAMPLE_REPORT_URL
from mining_rights_daily.pdfparse.document import extract_text
from mining_rights_daily.pdfparse.sample_pdf import build_sample_pdf
from mining_rights_daily.pdfparse.service import extract_resources
from mining_rights_daily.prices.book import CONTRACTS, build_book
from mining_rights_daily.prices.service import get_price, get_trend

AS_OF = "2026-10-27"
QUERY = "给我生成一份关于 Pilbara 锂矿的今日简报"


def test_required_prompt_parses_pilbara_lithium() -> None:
    intent = parse_intent(QUERY, date(2026, 10, 27))
    assert intent.region == "pilbara"
    assert intent.commodity == "lithium"
    assert intent.news_days == 1
    assert intent.trend_days == 30
    assert intent.report_url == SAMPLE_REPORT_URL
    assert intent.news_query == "pilbara lithium"


def test_news_window_keeps_today_and_drops_other_commodities() -> None:
    result = search_news("Pilbara lithium", days=1, as_of=AS_OF, enable_live=False)
    titles = [item.title for item in result.items]
    assert len(titles) == 2
    assert any("shipments" in title for title in titles)
    assert any("offtake" in title for title in titles)
    assert all("Copper" not in title for title in titles)
    wider = search_news("Pilbara lithium", days=2, as_of=AS_OF, enable_live=False)
    assert any("water" in item.title for item in wider.items)


def test_news_rejects_empty_query_and_bad_window() -> None:
    with pytest.raises(DomainError):
        search_news("的", days=7, as_of=AS_OF, enable_live=False)
    with pytest.raises(DomainError):
        search_news("lithium", days=0, as_of=AS_OF, enable_live=False)


def test_fetch_fixture_and_missing_fixture() -> None:
    article = fetch_article("fixture://mining-rights-daily/news/pls-shipments-2026-10-27")
    assert "Port Hedland" in article.text
    with pytest.raises(DomainError):
        fetch_article("fixture://missing")


_ASX_PAYLOAD = b"""
{
  "data": {
    "displayName": "PLS GROUP LIMITED",
    "symbol": "PLS",
    "items": [
      {
        "announcementType": "QUARTERLY ACTIVITIES REPORT",
        "date": "2026-10-27T21:00:20.000Z",
        "documentKey": "2924-03153965-6A1351813",
        "headline": "September 2026 Quarterly Activities Report",
        "isPriceSensitive": true,
        "url": ""
      }
    ]
  }
}
"""


def test_asx_payload_uses_sydney_date_and_matches_pilbara_query() -> None:
    rows = parse_asx_announcements(_ASX_PAYLOAD)
    assert len(rows) == 1
    row = rows[0]
    assert row["published_at"] == "2026-10-28"
    assert row["source"] == "ASX"
    assert row["source_type"] == "announcement"
    assert row["url"] == (
        "https://asx.api.markitdigital.com/asx-research/1.0/file/"
        "2924-03153965-6A1351813?access_token=a"
    )
    assert "价格敏感" in row["body"]
    result = search_news(
        "Pilbara lithium",
        days=1,
        as_of="2026-10-28",
        enable_live=False,
        live_items=rows,
    )
    matched = [item for item in result.items if item.source_type == "announcement"]
    assert len(matched) == 1
    assert matched[0].title == "September 2026 Quarterly Activities Report"


def test_asx_payload_rejects_invalid_json() -> None:
    with pytest.raises(DomainError):
        parse_asx_announcements(b"not-json")


def test_asx_feed_survives_rss_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_clock: date) -> list[dict[str, str]]:
        raise DomainError("RSS 超时")

    def ok(_clock: date) -> list[dict[str, object]]:
        return parse_asx_announcements(_ASX_PAYLOAD)

    monkeypatch.setattr("mining_rights_daily.news.service._fetch_rss", boom)
    monkeypatch.setattr("mining_rights_daily.news.service._fetch_asx", ok)
    result = search_news("Pilbara lithium", days=1, as_of="2026-10-28", enable_live=True)
    assert any(item.source_type == "announcement" for item in result.items)
    assert any("RSS" in error for error in result.live_feed_errors)


def test_fetch_article_reads_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = build_sample_pdf()

    def fake_fetch(url: str, *, timeout: float, max_bytes: int) -> tuple[bytes, str]:
        assert url.startswith("https://asx.api.markitdigital.com/")
        assert timeout > 0
        assert max_bytes >= len(pdf)
        return pdf, f"{url} (application/pdf)"

    monkeypatch.setattr("mining_rights_daily.news.service.fetch_limited", fake_fetch)
    article = fetch_article(
        "https://asx.api.markitdigital.com/asx-research/1.0/file/example?access_token=a"
    )
    assert article.source_type == "announcement"
    assert "Indicated" in article.text


def test_announcement_is_labeled_in_the_briefing() -> None:
    intent = parse_intent(QUERY, date(2026, 10, 28))
    data = BriefingData(
        intent=intent,
        news={
            "query": "pilbara lithium",
            "days": 1,
            "as_of": "2026-10-28",
            "window_start": "2026-10-28",
            "items": [
                {
                    "title": "September 2026 Quarterly Activities Report",
                    "url": "https://asx.api.markitdigital.com/asx-research/1.0/file/example?access_token=a",
                    "source": "ASX",
                    "source_type": "announcement",
                    "published_at": "2026-10-28",
                    "snippet": "PLS GROUP LIMITED 季度活动报告。",
                }
            ],
            "live_feed_errors": ["mining.com RSS: 超时"],
        },
    )
    markdown = render_briefing(data)
    assert "公司公告" in markdown
    assert "在线来源没有并入" in markdown


def test_presentations_rank_after_other_same_day_items() -> None:
    rows = [
        {
            "title": "September Quarter FY27 Activities Presentation",
            "url": "https://asx.api.markitdigital.com/asx-research/1.0/file/presentation",
            "source": "ASX",
            "source_type": "announcement",
            "published_at": "2026-10-28",
            "body": "slide deck",
            "keywords": ["pilbara", "lithium"],
        },
        {
            "title": "September 2026 Quarterly Activities Report",
            "url": "https://asx.api.markitdigital.com/asx-research/1.0/file/quarterly",
            "source": "ASX",
            "source_type": "announcement",
            "published_at": "2026-10-28",
            "body": "activities report",
            "keywords": ["pilbara", "lithium"],
        },
    ]
    result = search_news(
        "Pilbara lithium",
        days=1,
        as_of="2026-10-28",
        enable_live=False,
        live_items=rows,
    )
    titles = [item.title for item in result.items]
    assert titles.index("September 2026 Quarterly Activities Report") < titles.index(
        "September Quarter FY27 Activities Presentation"
    )


def test_asx_pdf_text_drops_letterhead() -> None:
    raw = (
        "TEL: +61 8 6266 6266 FAX: +61 8 6266 6288 "
        "ASX Announcement ASX: PLS 28 October 2026 "
        "September 2026 Quarterly Activities Report SUMMARY"
    )
    assert _strip_asx_letterhead(raw).startswith("September 2026 Quarterly Activities Report")


def test_rss_fetch_identifies_itself_and_waits_long_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake(url: str, *, timeout: float, max_bytes: int, headers: dict[str, str] | None = None):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["headers"] = headers
        assert max_bytes > 0
        return b"<rss></rss>", "ok"

    monkeypatch.setattr("mining_rights_daily.news.service.fetch_limited", fake)
    from mining_rights_daily.news.service import _fetch_rss

    assert _fetch_rss(date(2026, 10, 28)) == []
    assert captured["url"] == "https://www.mining.com/feed/"
    assert captured["timeout"] >= 8
    sent = captured["headers"]
    assert isinstance(sent, dict)
    assert "Mozilla" in sent["User-Agent"]
    assert "mining-rights-daily" in sent["User-Agent"]


def test_asx_fetch_waits_long_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, float] = {}

    def fake(url: str, *, timeout: float, max_bytes: int, headers: dict[str, str] | None = None):
        captured["timeout"] = timeout
        assert url.startswith("https://asx.api.markitdigital.com/")
        assert max_bytes > 0
        assert headers is None
        return _ASX_PAYLOAD, "ok"

    monkeypatch.setattr("mining_rights_daily.news.service.fetch_limited", fake)
    from mining_rights_daily.news.service import _fetch_asx

    rows = _fetch_asx(date(2026, 10, 28))
    assert rows[0]["title"] == "September 2026 Quarterly Activities Report"
    assert captured["timeout"] >= 15


def test_rss_items_can_be_merged_without_network() -> None:
    live = [
        {
            "title": "Pilbara lithium port note from a feed",
            "url": "https://www.mining.com/example-pilbara-lithium",
            "source": "mining.com",
            "source_type": "rss",
            "published_at": AS_OF,
            "body": "A Pilbara lithium item supplied by the test double.",
            "keywords": ["pilbara", "lithium"],
        }
    ]
    result = search_news("Pilbara lithium", days=1, as_of=AS_OF, enable_live=False, live_items=live)
    assert any(item.source_type == "rss" for item in result.items)


def test_sample_pdf_extracts_indicated_and_inferred() -> None:
    from mining_rights_daily.pdfparse.document import extract_pdf_bytes

    parsed = extract_pdf_bytes(build_sample_pdf(), SAMPLE_REPORT_URL)
    by_category = {row.category: row for row in parsed.rows}
    assert parsed.is_synthetic is True
    assert parsed.effective_date == "2024-06-30"
    assert parsed.project == "Pilgangoora Lithium Operation"
    assert by_category["Indicated"].tonnes_mt == 108.4
    assert by_category["Indicated"].grade_pct == 1.26
    assert by_category["Indicated"].contained_kt == 1366
    assert by_category["Inferred"].tonnes_mt == 53.1
    assert by_category["Proven"].kind == "reserve"
    assert by_category["Probable"].tonnes_mt == 74.8


def test_catalog_pdf_round_trip() -> None:
    parsed = extract_resources(SAMPLE_REPORT_URL)
    assert any(row.category == "Inferred" for row in parsed.rows)


def test_prose_resource_sentence() -> None:
    text = (
        "NI 43-101 note. Project: Example. "
        "The Indicated mineral resource is 10.5 million tonnes at 1.10% Li2O."
    )
    parsed = extract_text(text, "memory://example")
    assert parsed.rows[0].category == "Indicated"
    assert parsed.rows[0].tonnes_mt == 10.5
    assert parsed.rows[0].grade_label == "Li2O %"


def test_price_book_endpoints_and_weekend_rollback() -> None:
    import json

    from mining_rights_daily.paths import PRICE_PATH

    book = build_book()
    assert json.loads(PRICE_PATH.read_text(encoding="utf-8")) == book
    lithium = book["series"]["lithium"]["points"]
    assert lithium[0]["date"] == "2026-09-01"
    assert lithium[-1]["date"] == "2026-10-28"
    anchored = next(point for point in lithium if point["date"] == "2026-10-27")
    assert lithium[0]["close"] == CONTRACTS["lithium"]["start"]
    assert anchored["close"] == CONTRACTS["lithium"]["end"]
    quote = get_price("锂", AS_OF)
    assert quote.commodity == "lithium"
    assert quote.close == 10460
    assert quote.resolved_date == AS_OF
    weekend = get_price("lithium", "2026-10-25")
    assert weekend.resolved_date == "2026-10-23"
    assert weekend.note and "不是交易日" in weekend.note
    later = get_price("lithium", "2027-01-01")
    assert later.resolved_date == "2026-10-28"
    assert later.note and "更晚" in later.note


def test_trend_direction_and_unknown_commodity() -> None:
    trend = get_trend("lithium", 30)
    assert trend.direction == "down"
    assert trend.change_pct <= -5
    assert len(trend.points) == 30
    with pytest.raises(DomainError):
        get_price("unobtainium", AS_OF)


def test_health_payload_names_the_service() -> None:
    from mining_rights_daily.servers.bootstrap import health_payload

    assert health_payload("mining-news") == {"status": "ok", "service": "mining-news"}


def test_public_url_guard() -> None:
    assert assert_public_http("https://www.mining.com/feed/")
    with pytest.raises(DomainError):
        assert_public_http("http://127.0.0.1/secret")
    with pytest.raises(DomainError):
        assert_public_http("file:///etc/passwd")


def test_negated_watch_words_do_not_become_risks() -> None:
    from mining_rights_daily.agent.render import watch_hits

    text = (
        "No suspension, force majeure, or heritage stoppage is included in this fixture. "
        "Counterparties are still discussing 2027 offtake volumes."
    )
    needles = [needle for needle, _message in watch_hits(text)]
    assert needles == ["offtake"]
