from __future__ import annotations

from datetime import datetime

from .credibility_score import score_event_credibility, source_label
from .event_schema import AlertDecision, BeidouEvent

NEGATIVE_EVENT_TYPES = {"dilution/ATM/S-3", "geopolitical/oil/liquidity"}
DEFENSIVE_EVENT_TYPES = {"SEC filing", "earnings", "guidance", "macro data"}
CRITICAL_WEEKEND_TYPES = {"SEC filing", "macro data", "geopolitical/oil/liquidity", "dilution/ATM/S-3"}


def normalize_symbols(symbols: set[str] | list[str] | tuple[str, ...]) -> set[str]:
    return {str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()}


def classify_position_scope(event: BeidouEvent, actual_holdings: set[str], watchlist: set[str]) -> str:
    actual = normalize_symbols(actual_holdings)
    watch = normalize_symbols(watchlist)
    ticker = event.ticker.upper().strip()
    if ticker and ticker in actual:
        return "actual_holding"
    if ticker and ticker in watch:
        return "watchlist"
    return "excluded"


def classify_event(
    event: BeidouEvent,
    *,
    actual_holdings: set[str] | list[str] | tuple[str, ...],
    watchlist: set[str] | list[str] | tuple[str, ...],
    is_weekend_or_holiday: bool = False,
) -> AlertDecision:
    scope = classify_position_scope(event, set(actual_holdings), set(watchlist))
    event.position_scope = scope
    credibility = score_event_credibility(event)
    label = source_label(event)
    if is_weekend_or_holiday and event.event_type not in CRITICAL_WEEKEND_TYPES:
        return AlertDecision(scope, "中性", "只看", "休市日只保留重大官方/系统性风险。", False, False, label)
    if event.only_social or event.source_kind == "social":
        return AlertDecision(scope, "中性", "只看", "只有社媒来源，必须等待官方、IR、可靠新闻或量价确认。", False, True, label)
    if event.staleness_flag or credibility < 0.5:
        return AlertDecision(scope, "中性", "等30-60分钟", "来源过期、字段缺失或可信度不足。", False, True, label)
    if scope == "actual_holding":
        if event.event_type in NEGATIVE_EVENT_TYPES:
            return AlertDecision(scope, "利空", "减风险", "跟踪标的遇到官方/高可信风险事件。", True, True, label)
        if event.event_type in DEFENSIVE_EVENT_TYPES:
            return AlertDecision(scope, "中性", "等30-60分钟", "跟踪标的先看量价和后续文件确认。", True, True, label)
        return AlertDecision(scope, "中性", "只看", "跟踪标的相关，但尚未通过高质量催化过滤。", False, True, label)
    if scope == "watchlist":
        if event.has_official_anchor or event.event_type in {"earnings", "guidance", "index inclusion/removal"}:
            return AlertDecision(scope, "中性", "分批研究", "观察池出现高质量新催化，进入研究而非持仓提醒。", True, True, label)
        return AlertDecision(scope, "中性", "只看", "观察池普通线索，等待官方或量价确认。", False, True, label)
    return AlertDecision(scope, "中性", "只看", "不在观察池，默认排除。", False, False, label)


def is_today_new(event: BeidouEvent, now: datetime) -> bool:
    return event.published_time.astimezone(now.tzinfo).date() == now.date()
