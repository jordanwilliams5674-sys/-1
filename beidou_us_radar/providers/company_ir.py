from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..core.event_schema import BeidouEvent
from ..core.source_health import SourceHealthResult, check_payload_health


@dataclass(slots=True)
class IRSource:
    ticker: str
    company: str
    url: str
    source_type: str = "rss_or_newsroom"


def ir_health(payload: dict | None, now: datetime | None = None) -> SourceHealthResult:
    return check_payload_health(
        "Company IR",
        payload,
        required_fields=["ticker", "title", "url", "timestamp"],
        max_age=timedelta(days=14),
        now=now,
    )


def ir_event(payload: dict) -> BeidouEvent:
    text = f"{payload.get('title', '')} {payload.get('summary', '')}".lower()
    if "guidance" in text or "outlook" in text:
        event_type = "guidance"
        tags = ["new_guidance"]
    elif "earnings" in text or "results" in text:
        event_type = "earnings"
        tags = ["new_official_file"]
    elif "order" in text or "contract" in text or "partnership" in text:
        event_type = "AI infrastructure"
        tags = ["new_order"]
    else:
        event_type = "earnings"
        tags = []
    return BeidouEvent(
        ticker=str(payload.get("ticker", "")).upper(),
        company_person=str(payload.get("company") or ""),
        event_type=event_type,
        title=str(payload.get("title") or ""),
        description=str(payload.get("summary") or ""),
        source="Company IR",
        published_time=payload.get("timestamp"),
        collected_at=datetime.now(timezone.utc),
        credibility=0.95,
        source_tier="official",
        source_kind="company_ir",
        official_url=str(payload.get("url") or ""),
        tags=tags,
        raw=payload,
    )
