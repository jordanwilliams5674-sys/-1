from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

from ..core.event_schema import BeidouEvent
from ..core.source_health import SourceHealthResult, check_payload_health

HIGH_TRUST_NEWS = {"Reuters", "Bloomberg", "WSJ", "CNBC", "FT", "AP", "MarketWatch"}
NEWS_USER_AGENT = "beidou-us-radar-news/1.0"


def parse_feed_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_rss_titles(url: str, timeout: int = 15) -> list[dict]:
    req = Request(url, headers={"User-Agent": NEWS_USER_AGENT})
    with urlopen(req, timeout=timeout) as response:
        root = ET.fromstring(response.read())
    out = []
    for item in root.findall(".//item"):
        title = "".join(item.findtext("title") or "").strip()
        link = "".join(item.findtext("link") or "").strip()
        published = parse_feed_time(item.findtext("pubDate"))
        out.append({"title": title, "url": link, "timestamp": published.isoformat()})
    return out


def news_health(payload: dict | None, now: datetime | None = None) -> SourceHealthResult:
    return check_payload_health(
        "news_rss",
        payload,
        required_fields=["title", "url", "timestamp", "source"],
        max_age=timedelta(days=2),
        now=now,
    )


def news_event(payload: dict) -> BeidouEvent:
    source = str(payload.get("source") or "news")
    return BeidouEvent(
        ticker=str(payload.get("ticker") or "").upper(),
        sector=str(payload.get("sector") or ""),
        company_person=str(payload.get("company") or payload.get("person") or ""),
        event_type=str(payload.get("event_type") or "unusual price/volume/options"),
        title=str(payload.get("title") or ""),
        description=str(payload.get("summary") or ""),
        source=source,
        published_time=payload.get("timestamp"),
        collected_at=datetime.now(timezone.utc),
        credibility=0.72 if source in HIGH_TRUST_NEWS else 0.55,
        source_tier="news",
        source_kind="reliable_news" if source in HIGH_TRUST_NEWS else "news",
        official_url=str(payload.get("url") or ""),
        raw=payload,
    )
