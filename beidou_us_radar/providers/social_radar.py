from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core.event_schema import BeidouEvent
from ..core.source_health import SourceHealthResult, check_payload_health

SOCIAL_PLATFORMS = {"X", "Twitter", "Reddit", "YouTube", "Stocktwits", "Serenity"}


def social_health(payload: dict | None, now: datetime | None = None) -> SourceHealthResult:
    return check_payload_health(
        "social_radar",
        payload,
        required_fields=["platform", "text", "timestamp"],
        max_age=timedelta(days=2),
        now=now,
    )


def social_event(payload: dict) -> BeidouEvent:
    platform = str(payload.get("platform") or "social")
    return BeidouEvent(
        ticker=str(payload.get("ticker") or "").upper(),
        sector=str(payload.get("sector") or ""),
        company_person=str(payload.get("author") or payload.get("person") or ""),
        event_type=str(payload.get("event_type") or "unusual price/volume/options"),
        title=str(payload.get("text") or ""),
        description="社媒早期线索，未确认。",
        source=platform,
        published_time=payload.get("timestamp") or datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
        credibility=0.25,
        source_tier="signal",
        source_kind="social",
        only_social=True,
        raw=payload,
    )
