from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from mining_rights_daily.errors import DomainError
from mining_rights_daily.prices.book import load_book

ALIASES = {
    "lithium": "lithium",
    "li": "lithium",
    "lioh": "lithium",
    "锂": "lithium",
    "锂矿": "lithium",
    "spodumene": "lithium",
    "copper": "copper",
    "cu": "copper",
    "铜": "copper",
    "nickel": "nickel",
    "ni": "nickel",
    "镍": "nickel",
    "gold": "gold",
    "au": "gold",
    "金": "gold",
    "iron": "iron_ore",
    "iron_ore": "iron_ore",
    "iron-ore": "iron_ore",
    "fe": "iron_ore",
    "铁矿": "iron_ore",
}

SPODUMENE_NOTE = "请求的是辉石（spodumene）。返回的是氢氧化锂参考价，两者不是同一个合约，不能直接对比。"


class PriceQuote(BaseModel):
    commodity: str
    requested_commodity: str
    requested_date: str
    resolved_date: str
    close: float
    previous_close: float | None
    day_change_pct: float | None
    unit: str
    contract: str
    source: str
    disclaimer: str
    note: str | None = None


class TrendPoint(BaseModel):
    date: str
    close: float


class Trend(BaseModel):
    commodity: str
    requested_commodity: str
    days: int
    unit: str
    contract: str
    source: str
    disclaimer: str
    start_date: str
    end_date: str
    start: float
    end: float
    change: float
    change_pct: float
    high: float
    low: float
    direction: str
    note: str | None = None
    points: list[TrendPoint] = Field(default_factory=list)


def get_price(commodity: str, on_date: str) -> PriceQuote:
    canon, note, requested = _resolve(commodity)
    spec, points = _series(canon)
    requested_day = date.today() if on_date.strip().lower() == "today" else _parse_day(on_date)
    chosen, extra = _resolve_session(points, requested_day)
    notes = [part for part in (note, extra) if part]
    previous = _previous(points, chosen["date"])
    close = float(chosen["close"])
    day_change = None if previous is None else _pct(close, float(previous["close"]))
    return PriceQuote(
        commodity=canon,
        requested_commodity=requested,
        requested_date=requested_day.isoformat(),
        resolved_date=str(chosen["date"]),
        close=close,
        previous_close=None if previous is None else float(previous["close"]),
        day_change_pct=day_change,
        unit=str(spec["unit"]),
        contract=str(spec["contract"]),
        source=str(_book()["source"]),
        disclaimer=str(_book()["disclaimer"]),
        note=" ".join(notes) or None,
    )


def get_trend(commodity: str, days: int) -> Trend:
    if days < 2:
        raise DomainError("days 至少为 2，否则没有走势")
    canon, note, requested = _resolve(commodity)
    spec, points = _series(canon)
    if days > len(points):
        raise DomainError(f"days={days} 超过参考序列长度 {len(points)}")
    window = points[-days:]
    start = float(window[0]["close"])
    end = float(window[-1]["close"])
    closes = [float(point["close"]) for point in window]
    change = round(end - start, 2)
    change_pct = _pct(end, start)
    if change_pct > 1:
        direction = "up"
    elif change_pct < -1:
        direction = "down"
    else:
        direction = "flat"
    return Trend(
        commodity=canon,
        requested_commodity=requested,
        days=days,
        unit=str(spec["unit"]),
        contract=str(spec["contract"]),
        source=str(_book()["source"]),
        disclaimer=str(_book()["disclaimer"]),
        start_date=str(window[0]["date"]),
        end_date=str(window[-1]["date"]),
        start=start,
        end=end,
        change=change,
        change_pct=change_pct,
        high=max(closes),
        low=min(closes),
        direction=direction,
        note=note,
        points=[TrendPoint(date=str(point["date"]), close=float(point["close"])) for point in window],
    )


def _book() -> dict[str, object]:
    return load_book()


def _series(commodity: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    series = _book()["series"]
    if not isinstance(series, dict) or commodity not in series:
        raise DomainError(f"参考序列里没有 {commodity}")
    spec = series[commodity]
    if not isinstance(spec, dict):
        raise DomainError(f"参考序列 {commodity} 格式错误")
    points = spec.get("points")
    if not isinstance(points, list) or not points:
        raise DomainError(f"参考序列 {commodity} 没有交易日")
    return spec, points


def _resolve(commodity: str) -> tuple[str, str | None, str]:
    requested = commodity.strip()
    key = requested.lower()
    if key not in ALIASES:
        choices = "lithium, copper, nickel, gold, iron_ore"
        raise DomainError(f"不支持的商品 {commodity!r}。可选: {choices}")
    note = SPODUMENE_NOTE if key == "spodumene" else None
    return ALIASES[key], note, requested


def _resolve_session(
    points: list[dict[str, object]], requested: date
) -> tuple[dict[str, object], str | None]:
    last = date.fromisoformat(str(points[-1]["date"]))
    first = date.fromisoformat(str(points[0]["date"]))
    if requested > last:
        return points[-1], (
            f"参考序列截至 {last.isoformat()}，请求日 {requested.isoformat()} 更晚，已改用最后交易日。"
        )
    chosen = None
    for point in points:
        session = date.fromisoformat(str(point["date"]))
        if session <= requested:
            chosen = point
        else:
            break
    if chosen is None:
        raise DomainError(
            f"请求日 {requested.isoformat()} 早于参考序列起点 {first.isoformat()}"
        )
    resolved = date.fromisoformat(str(chosen["date"]))
    note = None
    if resolved != requested:
        note = f"{requested.isoformat()} 不是交易日，已回退到 {resolved.isoformat()}。"
    return chosen, note


def _previous(points: list[dict[str, object]], session: str) -> dict[str, object] | None:
    prior = None
    for point in points:
        if str(point["date"]) == session:
            return prior
        prior = point
    return None


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise DomainError("date 需要 YYYY-MM-DD，或字面量 today") from exc


def _pct(current: float, base: float) -> float:
    if base == 0:
        return 0.0
    return round((current - base) / base * 100, 2)
