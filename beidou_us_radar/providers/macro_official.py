from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..core.event_schema import BeidouEvent
from ..core.source_health import SourceHealthResult, check_payload_health


@dataclass(slots=True)
class MacroSource:
    name: str
    url: str
    category: str
    use_case: str


OFFICIAL_MACRO_SOURCES = [
    MacroSource("FRED", "https://fred.stlouisfed.org", "macro", "rates, dollar liquidity, real rates"),
    MacroSource("BLS", "https://www.bls.gov", "macro", "CPI, payrolls, unemployment, wages"),
    MacroSource("BEA", "https://www.bea.gov", "macro", "GDP, PCE"),
    MacroSource("U.S. Treasury", "https://home.treasury.gov", "macro", "Treasury yields and funding"),
    MacroSource("Federal Reserve", "https://www.federalreserve.gov", "macro", "FOMC, speeches, balance sheet"),
]


def macro_health(payload: dict | None, now: datetime | None = None) -> SourceHealthResult:
    return check_payload_health(
        "official_macro",
        payload,
        required_fields=["indicator", "value", "timestamp", "source"],
        max_age=timedelta(days=7),
        now=now,
    )


def macro_event(payload: dict) -> BeidouEvent:
    return BeidouEvent(
        ticker="",
        sector="USMARKET",
        company_person=str(payload.get("indicator") or "US macro"),
        event_type="macro data",
        title=str(payload.get("title") or payload.get("indicator") or "US macro data"),
        description=str(payload.get("summary") or ""),
        source=str(payload.get("source") or "official_macro"),
        published_time=payload.get("timestamp") or datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
        credibility=0.95,
        source_tier="official",
        source_kind="macro_official",
        official_url=str(payload.get("url") or ""),
        tags=["new_official_file"],
        raw=payload,
    )
