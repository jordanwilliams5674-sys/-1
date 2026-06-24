from __future__ import annotations

from .event_schema import BeidouEvent

SOURCE_BASE_SCORE = {
    "sec": 1.0,
    "company_ir": 0.95,
    "macro_official": 0.95,
    "exchange": 0.9,
    "reliable_news": 0.72,
    "market_data": 0.62,
    "akshare_aux": 0.45,
    "social": 0.25,
}


def source_kind_score(source_kind: str) -> float:
    return SOURCE_BASE_SCORE.get(source_kind, 0.35)


def score_event_credibility(event: BeidouEvent) -> float:
    if event.credibility:
        base = event.credibility
    elif event.sources:
        base = max(source.credibility for source in event.sources)
    else:
        base = source_kind_score(event.source_kind)
    if event.staleness_flag:
        base -= 0.2
    if event.only_social:
        base = min(base, SOURCE_BASE_SCORE["social"])
    if event.has_official_anchor:
        base = max(base, 0.9)
    return round(max(0.0, min(1.0, base)), 3)


def source_label(event: BeidouEvent) -> str:
    if event.has_official_anchor:
        return "官方/权威源"
    if event.only_social or event.source_kind == "social":
        return "社媒早期线索/未确认"
    if event.source_kind == "reliable_news":
        return "高可信新闻源"
    if event.source_kind in {"market_data", "akshare_aux"}:
        return "行情/辅助源"
    return "未确认"
