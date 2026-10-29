from __future__ import annotations

import json
from datetime import date, timedelta

from mining_rights_daily.paths import PRICE_PATH

DISCLAIMER = (
    "Bundled reference series for offline briefings. "
    "It is not an LME official settlement, not a Fastmarkets assessment, "
    "and must not be used as a trading price."
)

SERIES_START = date(2026, 9, 1)
ANCHOR_END = date(2026, 10, 27)
SERIES_END = date(2026, 10, 28)

CONTRACTS: dict[str, dict[str, object]] = {
    "lithium": {
        "unit": "USD/t",
        "contract": "Reference lithium hydroxide (demonstration series, not an LME settlement)",
        "start": 11840.0,
        "end": 10460.0,
    },
    "copper": {
        "unit": "USD/t",
        "contract": "Reference copper (demonstration series, not an LME settlement)",
        "start": 9620.0,
        "end": 10080.0,
    },
    "nickel": {
        "unit": "USD/t",
        "contract": "Reference nickel (demonstration series, not an LME settlement)",
        "start": 16850.0,
        "end": 16110.0,
    },
    "gold": {
        "unit": "USD/oz",
        "contract": "Reference gold (demonstration series, not an LBMA or COMEX settlement)",
        "start": 3380.0,
        "end": 3465.0,
    },
    "iron_ore": {
        "unit": "USD/t",
        "contract": "Reference 62% Fe iron ore (demonstration series, not a futures settlement)",
        "start": 104.5,
        "end": 98.0,
    },
}


def business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def build_book() -> dict[str, object]:
    anchor_days = business_days(SERIES_START, ANCHOR_END)
    extra_days = business_days(ANCHOR_END + timedelta(days=1), SERIES_END)
    series: dict[str, object] = {}
    for name, spec in CONTRACTS.items():
        start = float(spec["start"])
        end = float(spec["end"])
        count = len(anchor_days)
        slope = 0.0 if count <= 1 else (end - start) / (count - 1)
        points = []
        for index, day in enumerate(anchor_days):
            close = start if count == 1 else round(start + slope * index, 2)
            points.append({"date": day.isoformat(), "close": close})
        for index, day in enumerate(extra_days, start=1):
            points.append({"date": day.isoformat(), "close": round(end + slope * index, 2)})
        series[name] = {
            "unit": spec["unit"],
            "contract": spec["contract"],
            "points": points,
        }
    return {
        "source": "bundled-reference-series",
        "disclaimer": DISCLAIMER,
        "series": series,
    }


def load_book() -> dict[str, object]:
    if PRICE_PATH.exists():
        return json.loads(PRICE_PATH.read_text(encoding="utf-8"))
    return build_book()


def write_book() -> None:
    PRICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRICE_PATH.write_text(json.dumps(build_book(), indent=2) + "\n", encoding="utf-8")
