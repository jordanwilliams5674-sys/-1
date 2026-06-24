from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .alert_classifier import classify_event
from .beidou_formatter import format_mobile_alert
from .credibility_score import score_event_credibility, source_label
from .event_dedupe import DedupeStore
from .event_schema import BeidouEvent, parse_dt
from .source_health import check_payload_health

ROOT = Path(__file__).resolve().parents[2]
ACCOUNTS_PATH = ROOT / "data" / "holdings_accounts" / "accounts.json"
WATCHLIST_PATH = ROOT / "config" / "watchlist.yaml"

DISABLED_A_SHARE_SOURCES = [
    {"name": "mootdx", "status": "disabled", "reason": "A股通达信 TCP 数据源，只适合 A 股 K线、盘口、F10。"},
    {"name": "同花顺热点", "status": "disabled", "reason": "A股题材热度和强势股接口。"},
    {"name": "百度股市通 PAE", "status": "disabled", "reason": "主要用于 A股概念、资金流和 K线。"},
    {"name": "iwencai", "status": "disabled", "reason": "A股自然语言选股且需要鉴权。"},
    {"name": "Ashare", "status": "disabled", "reason": "教学项目，停更风险高。"},
    {"name": "tushare", "status": "disabled_as_core", "reason": "不作为核心源；只能低优先级备选并做鉴权、字段和延迟检查。"},
]

OFFICIAL_PLATFORMS = {"SEC EDGAR", "SEC监管", "美联储公告", "美联储讲话", "美联储证词", "Federal Reserve", "Company IR"}
RELIABLE_NEWS_PLATFORMS = {
    "Reuters",
    "Bloomberg",
    "WSJ",
    "CNBC",
    "CNBC市场资讯",
    "FT",
    "AP",
    "MarketWatch",
    "MarketWatch市场资讯",
    "Yahoo Finance资讯",
    "Yahoo Finance RSS",
}
SOCIAL_PLATFORMS = {"X", "Twitter", "Reddit", "YouTube", "Stocktwits", "Serenity"}
US_MARKET_SYMBOLS = {"USMARKET", "GOLD_BASKET", ""}


def valid_us_symbol(symbol: str) -> bool:
    if symbol in US_MARKET_SYMBOLS:
        return True
    return re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol or "") is not None


def load_actual_holdings(path: Path = ACCOUNTS_PATH) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    holdings = payload.get("持仓列表", [])
    out = set()
    if isinstance(holdings, list):
        for item in holdings:
            if not isinstance(item, dict):
                continue
            qty = item.get("数量", 0)
            try:
                qty_number = float(qty)
            except Exception:
                qty_number = 0.0
            symbol = str(item.get("股票代码") or "").upper().strip()
            if qty_number > 0 and valid_us_symbol(symbol):
                out.add(symbol)
    return out


def load_watchlist(path: Path = WATCHLIST_PATH) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*-\s*ticker:\s*([A-Za-z0-9.=_^-]+)", line)
        if not match:
            continue
        symbol = match.group(1).upper().strip()
        if valid_us_symbol(symbol):
            out.add(symbol)
    return out


def event_type_from_text(text: str, fallback: str = "unusual price/volume/options") -> str:
    low = text.lower()
    if any(term in low for term in ["s-3", "424b", "atm", "offering", "dilution", "增发"]):
        return "dilution/ATM/S-3"
    if any(term in low for term in ["10-k", "10-q", "8-k", "sec", "edgar"]):
        return "SEC filing"
    if any(term in low for term in ["earnings", "财报", "results"]):
        return "earnings"
    if any(term in low for term in ["guidance", "outlook", "指引"]):
        return "guidance"
    if any(term in low for term in ["analyst", "rating", "price target", "评级"]):
        return "analyst action"
    if any(term in low for term in ["s&p 500", "index", "纳入", "剔除"]):
        return "index inclusion/removal"
    if any(term in low for term in ["form 4", "insider"]):
        return "insider transaction"
    if any(term in low for term in ["fed", "fomc", "cpi", "pce", "payroll", "treasury", "美联储", "非农", "收益率"]):
        return "macro data"
    if any(term in low for term in ["tariff", "solar", "关税", "太阳能"]):
        return "solar/tariff"
    if any(term in low for term in ["stablecoin", "crypto", "circle", "稳定币", "加密"]):
        return "crypto/stablecoin regulation"
    if any(term in low for term in ["ai", "data center", "compute", "infrastructure", "人工智能", "数据中心"]):
        return "AI infrastructure"
    if any(term in low for term in ["power", "electric", "nuclear", "smr", "电力", "核电"]):
        return "data-center power"
    if any(term in low for term in ["quantum", "量子"]):
        return "quantum"
    if any(term in low for term in ["oil", "geopolitical", "war", "sanction", "地缘", "制裁"]):
        return "geopolitical/oil/liquidity"
    if any(term in low for term in ["pepsi", "coca-cola", "consumer", "defensive", "百事", "可口可乐"]):
        return "defensive consumer"
    return fallback


def source_kind_for(source: str, note: str = "") -> tuple[str, str, float, bool]:
    text = f"{source} {note}"
    if source in OFFICIAL_PLATFORMS or any(term in text for term in OFFICIAL_PLATFORMS):
        return "official", "sec" if "SEC" in text else "macro_official", 0.95, False
    if source in SOCIAL_PLATFORMS:
        return "signal", "social", 0.25, True
    if source in RELIABLE_NEWS_PLATFORMS or any(term in text for term in RELIABLE_NEWS_PLATFORMS):
        return "news", "reliable_news", 0.72, False
    if "akshare" in text.lower():
        return "auxiliary", "akshare_aux", 0.45, False
    if any(term in text for term in ["TradingView", "Yahoo chart", "Yahoo Finance quote", "行情"]):
        return "auxiliary", "market_data", 0.62, False
    return "news", "news", 0.5, False


def candidate_events(payload: dict[str, Any]) -> list[BeidouEvent]:
    out: list[BeidouEvent] = []
    source_rows = list(payload.get("重要置顶", []) or []) + list(payload.get("候选股票", []) or [])
    for item in source_rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("股票代码") or "").upper().strip()
        if not valid_us_symbol(symbol) or symbol in {"", "USMARKET"}:
            continue
        catalysts = item.get("催化来源") or []
        first = catalysts[0] if catalysts and isinstance(catalysts[0], dict) else {}
        quote = item.get("当前行情") or {}
        title = str(first.get("中文标题") or first.get("标题") or item.get("事件标注") or item.get("公司名称") or symbol)
        source = str(first.get("来源") or quote.get("数据源") or "北斗扫描")
        timestamp = first.get("发布时间") or payload.get("生成时间UTC")
        source_tier, source_kind, credibility, only_social = source_kind_for(source)
        official_url = str(first.get("网址") or "") if source_tier == "official" else ""
        event_type = event_type_from_text(f"{title} {first.get('催化类型') or ''} {item.get('事件标注') or ''}")
        out.append(
            BeidouEvent(
                ticker=symbol,
                company_person=str(item.get("公司名称") or symbol),
                event_type=event_type,
                title=title,
                description=str(item.get("事件标注") or ""),
                source=source,
                timestamp=timestamp,
                collected_at=payload.get("生成时间UTC"),
                credibility=credibility,
                source_tier=source_tier,
                source_kind=source_kind,
                only_social=only_social,
                price_move_pct=quote.get("当前涨跌幅"),
                volume_confirmation=bool(quote.get("当前成交量")),
                official_url=official_url,
                tags=["new_price_confirmation"] if quote.get("当前涨跌幅") is not None else [],
                raw={"source_payload": "候选股票", "original": item},
            )
        )
    return out


def social_events(signals: list[dict[str, Any]], generated_at: str | None = None) -> list[BeidouEvent]:
    out: list[BeidouEvent] = []
    for item in signals:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("股票代码") or "USMARKET").upper().strip()
        if not valid_us_symbol(symbol):
            continue
        source = str(item.get("平台") or "news")
        note = str(item.get("备注") or "")
        title = str(item.get("文字") or "")
        source_tier, source_kind, credibility, only_social = source_kind_for(source, note)
        out.append(
            BeidouEvent(
                ticker="" if symbol == "USMARKET" else symbol,
                sector="USMARKET" if symbol == "USMARKET" else "",
                company_person=str(item.get("作者") or symbol or "USMARKET"),
                event_type=event_type_from_text(f"{title} {note} {source}"),
                title=title,
                description=note,
                source=source,
                timestamp=item.get("发布时间") or generated_at,
                collected_at=generated_at,
                credibility=credibility,
                source_tier=source_tier,
                source_kind=source_kind,
                only_social=only_social,
                official_url=str(item.get("原帖链接") or ""),
                raw={"source_payload": "社媒信号", "original": item},
            )
        )
    return out


def health_summary(payload: dict[str, Any], social: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    generated = payload.get("生成时间UTC")
    candidates = list(payload.get("重要置顶", []) or []) + list(payload.get("候选股票", []) or [])
    checks = [
        check_payload_health(
            "SEC/IR official anchor",
            {"source": "SEC/IR", "timestamp": generated, "count": sum(1 for item in candidates for cat in item.get("催化来源", []) if str(cat.get("来源", "")).startswith(("SEC", "Company IR")))},
            ["source", "timestamp", "count"],
            now=now,
        ),
        check_payload_health(
            "market data",
            {"source": "TradingView/Yahoo/Finnhub", "timestamp": generated, "count": len(candidates)},
            ["source", "timestamp", "count"],
            now=now,
        ),
        check_payload_health(
            "news/social feed",
            {"source": "news/social", "timestamp": generated, "count": len(social)},
            ["source", "timestamp", "count"],
            now=now,
        ),
    ]
    return [
        {
            "数据源": item.source,
            "状态": item.status,
            "可用": item.ok,
            "staleness_flag": item.staleness_flag,
            "缺失字段": item.missing_fields,
            "异常字段": item.abnormal_fields,
            "检查时间UTC": item.checked_at.isoformat(),
        }
        for item in checks
    ]


def build_data_source_layer_payload(payload: dict[str, Any], social: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    social = social or []
    actual = load_actual_holdings()
    watch = load_watchlist() - actual
    store = DedupeStore()
    now = parse_dt(payload.get("生成时间UTC"), fallback=datetime.now(timezone.utc))
    events = candidate_events(payload) + social_events(social, payload.get("生成时间UTC"))
    classified = []
    alerts = []
    for event in events:
        if not store.accept(event, now=now):
            event.raw["duplicate"] = True
            continue
        event.raw["duplicate"] = False
        decision = classify_event(event, actual_holdings=actual, watchlist=watch)
        event.credibility = score_event_credibility(event)
        record = {
            "ticker": event.subject_key,
            "event_type": event.event_type,
            "title": event.title,
            "source": event.source,
            "timestamp": event.published_time.isoformat(),
            "credibility": event.credibility,
            "staleness_flag": event.staleness_flag,
            "source_label": source_label(event),
            "position_scope": decision.position_scope,
            "action": decision.action,
            "reason": decision.reason,
            "only_social": event.only_social,
            "can_trigger_trade_alert": decision.can_trigger_trade_alert,
        }
        classified.append(record)
        if decision.should_notify and len(alerts) < 3:
            alerts.append(format_mobile_alert(event, decision, reminder_time=now))
    source_layers = [
        {"层级": "官方/权威源", "用途": "SEC、IR、宏观、交易所/指数官方", "优先级": 1},
        {"层级": "行情和辅助源", "用途": "TradingView、Yahoo、akshare_us、可选商业API", "优先级": 2},
        {"层级": "新闻和发酵源", "用途": "Reuters/Bloomberg/WSJ/CNBC/FT/AP/MarketWatch 和社媒早期线索", "优先级": 3},
    ]
    return {
        "状态": "已接入",
        "范围": "美股全时段雷达",
        "实际持仓数量": len(actual),
        "观察池数量": len(watch),
        "禁用A股源": DISABLED_A_SHARE_SOURCES,
        "源分层": source_layers,
        "健康检查": health_summary(payload, social),
        "事件数量": len(classified),
        "事件流": classified[:40],
        "手机短版样例": alerts,
        "规则": {
            "事实锚": "SEC 和公司 IR 是公告、财报、增发、风险披露最高优先级源。",
            "行情限制": "行情只说明价格变化，不能替代公告或财报。",
            "社媒限制": "社媒-only 只看，不触发交易提醒。",
            "去重": "48小时内重复事件过滤；新官方文件、新指引、新订单、新评级、新量价确认可突破。",
        },
    }
