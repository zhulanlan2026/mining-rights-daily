from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mining_rights_daily.paths import SAMPLE_REPORT_URL

_COMMODITIES = (
    (("锂矿", "碳酸锂", "锂", "spodumene", "lithium"), "lithium"),
    (("铜", "copper"), "copper"),
    (("镍", "nickel"), "nickel"),
    (("铁矿", "iron ore", "iron_ore"), "iron_ore"),
    (("黄金", "金矿", "gold"), "gold"),
)
_REGIONS = ((("皮尔巴拉", "pilgangoora", "pilbara"), "pilbara"),)
_REPORTS = {("pilbara", "lithium"): SAMPLE_REPORT_URL}
_LABELS = {("pilbara", "lithium"): "Pilbara 锂矿（Pilgangoora）"}
_COMMODITY_LABELS = {
    "lithium": "锂",
    "copper": "铜",
    "nickel": "镍",
    "gold": "金",
    "iron_ore": "铁矿",
}


@dataclass(frozen=True)
class Intent:
    raw_query: str
    region: str | None
    commodity: str | None
    asset_label: str
    news_query: str
    news_days: int
    trend_days: int
    as_of: date
    report_url: str | None


def parse_intent(query: str, as_of: date) -> Intent:
    text = query.strip()
    lowered = text.lower()
    commodity = _first(_COMMODITIES, lowered)
    region = _first(_REGIONS, lowered)
    label = _LABELS.get((region, commodity))
    if label is None:
        parts = [part for part in (region, _COMMODITY_LABELS.get(commodity or "")) if part]
        label = " ".join(parts) or text
    news_terms = [part for part in (region, commodity) if part]
    news_query = " ".join(news_terms) or text
    news_days = 1 if any(word in text for word in ("今日", "今天", "today")) else 7
    return Intent(
        raw_query=text,
        region=region,
        commodity=commodity,
        asset_label=label,
        news_query=news_query,
        news_days=news_days,
        trend_days=30,
        as_of=as_of,
        report_url=_REPORTS.get((region, commodity)),
    )


def _first(rules: tuple[tuple[tuple[str, ...], str], ...], text: str) -> str | None:
    for needles, value in rules:
        if any(needle.lower() in text for needle in needles):
            return value
    return None
