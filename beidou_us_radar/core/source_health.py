from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .event_schema import parse_dt


@dataclass(slots=True)
class SourceHealthResult:
    source: str
    ok: bool
    staleness_flag: bool
    status: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    missing_fields: list[str] = field(default_factory=list)
    abnormal_fields: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    error: str = ""


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def check_payload_health(
    source: str,
    payload: dict[str, Any] | None,
    required_fields: Iterable[str],
    *,
    timestamp_field: str = "timestamp",
    max_age: timedelta = timedelta(minutes=20),
    now: datetime | None = None,
    latency_ms: int | None = None,
    error: str = "",
) -> SourceHealthResult:
    now = now or datetime.now(timezone.utc)
    if payload is None:
        return SourceHealthResult(source, False, True, "no_payload", latency_ms=latency_ms, error=error)
    missing = [field for field in required_fields if is_missing(payload.get(field))]
    abnormal: list[str] = []
    staleness = False
    timestamp_value = payload.get(timestamp_field)
    if is_missing(timestamp_value):
        missing.append(timestamp_field)
        staleness = True
    else:
        try:
            ts = parse_dt(timestamp_value)
            age = now - ts
            if age > max_age or age < -timedelta(minutes=5):
                staleness = True
                abnormal.append(timestamp_field)
        except Exception as exc:
            staleness = True
            abnormal.append(f"{timestamp_field}:{exc}")
    if latency_ms is not None and latency_ms > 5000:
        abnormal.append("latency_ms")
    ok = not missing and not abnormal and not error
    status = "ok" if ok else "stale_or_invalid" if staleness or missing else "degraded"
    return SourceHealthResult(
        source=source,
        ok=ok,
        staleness_flag=staleness or bool(missing),
        status=status,
        missing_fields=missing,
        abnormal_fields=abnormal,
        latency_ms=latency_ms,
        error=error,
    )


def merge_health(results: Iterable[SourceHealthResult]) -> SourceHealthResult:
    items = list(results)
    if not items:
        return SourceHealthResult("aggregate", False, True, "no_sources")
    ok = any(item.ok for item in items)
    stale = all(item.staleness_flag for item in items)
    missing: list[str] = []
    abnormal: list[str] = []
    errors: list[str] = []
    for item in items:
        missing.extend(item.missing_fields)
        abnormal.extend(item.abnormal_fields)
        if item.error:
            errors.append(f"{item.source}:{item.error}")
    return SourceHealthResult(
        "aggregate",
        ok,
        stale,
        "ok" if ok and not stale else "degraded",
        missing_fields=missing,
        abnormal_fields=abnormal,
        error="; ".join(errors),
    )
