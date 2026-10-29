from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mining_rights_daily.agent.intent import Intent
from mining_rights_daily.agent.protocol import Step


@dataclass
class BriefingData:
    intent: Intent
    steps: list[Step] = field(default_factory=list)
    news: dict[str, Any] | None = None
    news_error: str | None = None
    articles: list[dict[str, Any]] = field(default_factory=list)
    article_errors: list[str] = field(default_factory=list)
    resources: dict[str, Any] | None = None
    resources_error: str | None = None
    price: dict[str, Any] | None = None
    price_error: str | None = None
    trend: dict[str, Any] | None = None
    trend_error: str | None = None
