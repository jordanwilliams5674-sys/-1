from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_EVENT_TYPES = {
    "SEC filing",
    "earnings",
    "guidance",
    "analyst action",
    "index inclusion/removal",
    "insider transaction",
    "dilution/ATM/S-3",
    "macro data",
    "geopolitical/oil/liquidity",
    "unusual price/volume/options",
    "crypto/stablecoin regulation",
    "AI infrastructure",
    "data-center power",
    "quantum",
    "solar/tariff",
    "defensive consumer",
}

POSITION_SCOPES = {"actual_holding", "watchlist", "excluded"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: datetime | str | None, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    elif fallback is not None:
        parsed = fallback
    else:
        parsed = utc_now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class SourceMeta:
    source: str
    timestamp: datetime | str
    credibility: float
    staleness_flag: bool = False
    source_tier: str = "auxiliary"
    source_kind: str = "unknown"
    url: str = ""
    health_status: str = "unknown"

    def normalized_timestamp(self) -> datetime:
        return parse_dt(self.timestamp)


@dataclass(slots=True)
class BeidouEvent:
    ticker: str = ""
    sector: str = ""
    company_person: str = ""
    event_type: str = "unusual price/volume/options"
    title: str = ""
    description: str = ""
    source: str = ""
    timestamp: datetime | str | None = None
    published_time: datetime | str | None = None
    collected_at: datetime | str | None = None
    credibility: float = 0.0
    staleness_flag: bool = False
    source_tier: str = "auxiliary"
    source_kind: str = "unknown"
    position_scope: str = "excluded"
    sources: list[SourceMeta] = field(default_factory=list)
    only_social: bool = False
    price_move_pct: float | None = None
    volume_confirmation: bool = False
    official_url: str = ""
    tags: list[str] = field(default_factory=list)
    is_today_new: bool | None = None
    continuation_of_yesterday: bool = False
    priced_in: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ticker = self.ticker.upper().strip()
        self.sector = self.sector.strip()
        self.company_person = self.company_person.strip()
        if self.event_type not in VALID_EVENT_TYPES:
            self.event_type = "unusual price/volume/options"
        if self.position_scope not in POSITION_SCOPES:
            self.position_scope = "excluded"
        self.published_time = parse_dt(self.published_time or self.timestamp, fallback=utc_now())
        self.timestamp = self.published_time
        self.collected_at = parse_dt(self.collected_at, fallback=utc_now())

    @property
    def subject_key(self) -> str:
        return self.ticker or self.sector or "USMARKET"

    @property
    def has_official_anchor(self) -> bool:
        return self.source_tier == "official" or self.source_kind in {"sec", "company_ir", "macro_official", "exchange"} or bool(self.official_url)


@dataclass(slots=True)
class AlertDecision:
    position_scope: str
    conclusion: str
    action: str
    reason: str
    can_trigger_trade_alert: bool = False
    should_notify: bool = True
    source_label: str = "未确认"


def event_from_dict(payload: dict[str, Any]) -> BeidouEvent:
    return BeidouEvent(**payload)
