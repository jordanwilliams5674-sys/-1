from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core.event_schema import BeidouEvent
from ..core.source_health import SourceHealthResult, check_payload_health

QUOTE_REQUIRED_FIELDS = ["symbol", "price", "change_percent", "volume", "timestamp"]


def quote_health(payload: dict | None, now: datetime | None = None) -> SourceHealthResult:
    return check_payload_health(
        "market_data",
        payload,
        required_fields=QUOTE_REQUIRED_FIELDS,
        max_age=timedelta(minutes=20),
        now=now,
    )


def unusual_market_event(payload: dict, *, volume_confirmation: bool = False) -> BeidouEvent:
    tags = ["new_price_confirmation"] if payload.get("change_percent") is not None else []
    if volume_confirmation:
        tags.append("new_volume_confirmation")
    return BeidouEvent(
        ticker=str(payload.get("symbol") or "").upper(),
        event_type="unusual price/volume/options",
        title=f"{payload.get('symbol')} unusual price/volume",
        description=f"Price {payload.get('price')} change {payload.get('change_percent')} volume {payload.get('volume')}.",
        source=str(payload.get("source") or "market_data"),
        published_time=payload.get("timestamp") or datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
        credibility=0.62,
        source_tier="auxiliary",
        source_kind="market_data",
        price_move_pct=payload.get("change_percent"),
        volume_confirmation=volume_confirmation,
        tags=tags,
        raw=payload,
    )
