from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .alert_classifier import is_today_new
from .event_schema import AlertDecision, BeidouEvent, parse_dt

BJ = ZoneInfo("Asia/Shanghai")
ET = ZoneInfo("America/New_York")


def fmt_dt(value: datetime, zone: ZoneInfo) -> str:
    dt = value.astimezone(zone)
    return f"{dt.year}年{dt.month:02d}月{dt.day:02d}日 {dt.hour:02d}:{dt.minute:02d}"


def freshness_label(event: BeidouEvent, now: datetime) -> str:
    if event.continuation_of_yesterday:
        return "昨日事件延续"
    if is_today_new(event, now.astimezone(BJ)):
        return "今日新消息"
    return "旧消息"


def position_label(scope: str) -> str:
    return {
        "actual_holding": "跟踪标的",
        "watchlist": "观察池研究",
        "excluded": "排除",
    }.get(scope, "排除")


def priced_label(event: BeidouEvent) -> str:
    if event.priced_in is True:
        return "已计价"
    if event.priced_in is False:
        return "未完全计价"
    return "是否计价待确认"


def format_mobile_alert(event: BeidouEvent, decision: AlertDecision, reminder_time: datetime | None = None) -> str:
    now = parse_dt(reminder_time, fallback=parse_dt(event.collected_at))
    event_time = parse_dt(event.published_time)
    title = event.title or event.description or event.event_type
    relation = position_label(decision.position_scope)
    source = decision.source_label
    freshness = freshness_label(event, now)
    directness = "直接影响" if decision.position_scope == "actual_holding" else "间接/研究价值"
    duplicate = "重复性待去重系统确认"
    if event.raw.get("duplicate") is False:
        duplicate = "非48小时重复事件"
    elif event.raw.get("duplicate") is True:
        duplicate = "48小时内重复事件"
    return "\n".join(
        [
            "🚨【新消息｜北斗综合任务】",
            f"🕒【提醒时间】北京时间 {fmt_dt(now, BJ)} / 美东时间 {fmt_dt(now, ET)}",
            "",
            "【一句话结论】",
            f"{decision.conclusion} + {decision.action}。",
            "",
            "【事件链】",
            f"事件时间/消息发布时间：{fmt_dt(event_time, BJ)}。",
            f"{event.source or '未知来源'}：{title}。{event.description or '等待进一步原文确认。'}",
            f"来源可信度：{source}；{freshness} / {priced_label(event)}。",
            "",
            "【相关标的】",
            f"{relation}：{event.subject_key}；{directness}；{decision.conclusion}；{duplicate}；{priced_label(event)}。",
            "",
            "【操作】",
            f"{decision.action} + {decision.reason}",
        ]
    )
