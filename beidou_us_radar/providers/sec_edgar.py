from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.event_schema import BeidouEvent
from ..core.source_health import SourceHealthResult, check_payload_health

SEC_USER_AGENT = "beidou-us-radar/1.0 contact=295765031@qq.com"
SEC_FORMS = {"10-K", "10-Q", "8-K", "S-1", "S-3", "424B", "424B2", "424B3", "424B4", "424B5", "4", "13F-HR"}


def sec_request_json(url: str, timeout: int = 15) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def filing_health(payload: dict[str, Any] | None, now: datetime | None = None) -> SourceHealthResult:
    return check_payload_health(
        "SEC EDGAR",
        payload,
        required_fields=["ticker", "form", "accession_number", "filing_date", "timestamp"],
        now=now,
        max_age=timedelta(days=7),
    )


def filing_event(payload: dict[str, Any]) -> BeidouEvent:
    form = str(payload.get("form", "")).upper()
    event_type = "SEC filing"
    if form in {"S-3"} or form.startswith("424B"):
        event_type = "dilution/ATM/S-3"
    elif form == "4":
        event_type = "insider transaction"
    return BeidouEvent(
        ticker=str(payload.get("ticker", "")).upper(),
        company_person=str(payload.get("company") or payload.get("person") or ""),
        event_type=event_type,
        title=f"{payload.get('ticker')} {form} filing",
        description=str(payload.get("summary") or f"SEC EDGAR filed {form}."),
        source="SEC EDGAR",
        published_time=payload.get("timestamp") or payload.get("filing_date") or datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
        credibility=1.0,
        source_tier="official",
        source_kind="sec",
        official_url=str(payload.get("url") or ""),
        tags=["new_official_file"],
        raw=payload,
    )
