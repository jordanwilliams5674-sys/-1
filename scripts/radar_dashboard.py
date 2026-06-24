#!/usr/bin/env python3
"""Local auto-refresh dashboard for 北斗美股全时段异动雷达.

This local server only reads market/research data and writes local reports.
It is not an auto-trading system and never calls broker order APIs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
REPORT_DIR = ROOT / "reports" / "premarket"
IMPORTANT_STATE_PATH = REPORT_DIR / "important" / "important_records.json"
DASHBOARD_TEMPLATE = ROOT / "dashboard" / "index.html"
SOCIAL_SIGNAL_DIR = ROOT / "data" / "social_signals"
SOCIAL_MEDIA_DIR = SOCIAL_SIGNAL_DIR / "media"
WATCHLIST_CONFIG = ROOT / "config" / "watchlist.yaml"
HOLDINGS_ACCOUNTS_PATH = ROOT / "data" / "holdings_accounts" / "accounts.json"
LOG_DIR = ROOT / "logs"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from premarket_mover_scan import active_change_percent  # noqa: E402
from premarket_mover_scan import active_price  # noqa: E402
from premarket_mover_scan import active_session_label  # noqa: E402
from premarket_mover_scan import active_volume  # noqa: E402
from premarket_mover_scan import discover_yahoo_screeners  # noqa: E402
from premarket_mover_scan import fetch_tradingview_quotes  # noqa: E402
from premarket_mover_scan import fetch_yahoo_chart_quote  # noqa: E402
from premarket_mover_scan import fetch_yahoo_quotes  # noqa: E402
from premarket_mover_scan import market_session  # noqa: E402
from premarket_mover_scan import relation_maps  # noqa: E402
from premarket_mover_scan import run_scan  # noqa: E402

try:
    from cngold_member_scan import collect as collect_cngold_signals  # noqa: E402
    from cngold_member_scan import write_outputs as write_cngold_outputs  # noqa: E402
except Exception as exc:  # pragma: no cover - dashboard should still start without optional source.
    collect_cngold_signals = None
    write_cngold_outputs = None
    CNGOLD_IMPORT_ERROR = str(exc)
else:
    CNGOLD_IMPORT_ERROR = None

try:
    from beidou_us_radar.core.dashboard_bridge import build_data_source_layer_payload  # noqa: E402
except Exception as exc:  # pragma: no cover - dashboard should still run without the optional layer.
    build_data_source_layer_payload = None
    BEIDOU_SOURCE_LAYER_ERROR = str(exc)
else:
    BEIDOU_SOURCE_LAYER_ERROR = None

STATE = {
    "running": False,
    "last_scan_started": None,
    "last_scan_finished": None,
    "last_error": None,
    "last_report": None,
    "last_member_source_started": None,
    "last_member_source_finished": None,
    "last_member_source_error": None,
    "last_member_source_count": 0,
    "last_live_started": None,
    "last_live_finished": None,
    "last_live_error": None,
    "last_live_count": 0,
}
SCAN_LOCK = threading.Lock()
SCAN_ENABLED = True
LIVE_LOCK = threading.Lock()
LIVE_CACHE: dict[str, object] = {"payload": None, "updated_at": 0.0}
LIVE_TTL_SECONDS = 45
LIVE_MAX_SYMBOLS = 64
SOCIAL_MAX_AGE_SECONDS = 96 * 3600
MARKET_SENTIMENT_SYMBOLS = {
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "RSP",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLU",
    "SMH",
    "SOXX",
    "TLT",
    "HYG",
    "UUP",
    "GLD",
}
LIVE_CHART_FALLBACK_SYMBOLS = MARKET_SENTIMENT_SYMBOLS | {
    "SQQQ",
    "SOXS",
    "NVDA",
    "TSLA",
    "AMD",
    "AAPL",
    "MRVL",
    "MU",
    "INTC",
    "RGTI",
    "MSFT",
    "AMZN",
    "META",
    "GOOGL",
    "NFLX",
    "PLTR",
    "COIN",
    "MSTR",
    "TSM",
    "CRM",
    "ADBE",
    "SMCI",
}
INDEX_DEFINITIONS = [
    ("纳斯达克100", "QQQ"),
    ("标普500", "SPY"),
    ("道琼斯", "DIA"),
    ("罗素2000", "IWM"),
    ("科技板块", "XLK"),
    ("半导体", "SMH"),
]
LIVE_CORE_SYMBOLS = [
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "RSP",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLU",
    "SMH",
    "SOXX",
    "TLT",
    "HYG",
    "UUP",
    "GLD",
    "SQQQ",
    "SOXS",
    "NVDA",
    "TSLA",
    "AMD",
    "AVGO",
    "MRVL",
    "MU",
    "INTC",
    "MSFT",
    "AAPL",
    "AMZN",
    "META",
    "GOOGL",
    "ORCL",
    "NFLX",
    "PLTR",
    "COIN",
    "MSTR",
    "TSM",
    "CRM",
    "ADBE",
    "SMCI",
]


def log(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (LOG_DIR / "dashboard.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")
    except PermissionError:
        return


def sync_member_sources_safely() -> None:
    STATE["last_member_source_started"] = datetime.now().isoformat(timespec="seconds")
    STATE["last_member_source_error"] = None
    if collect_cngold_signals is None or write_cngold_outputs is None:
        STATE["last_member_source_error"] = CNGOLD_IMPORT_ERROR or "金投网源模块不可用"
        STATE["last_member_source_finished"] = datetime.now().isoformat(timespec="seconds")
        log(f"member source unavailable: {STATE['last_member_source_error']}")
        return
    try:
        signals = collect_cngold_signals(limit=60)
        write_cngold_outputs(signals)
        STATE["last_member_source_count"] = len(signals)
        STATE["last_member_source_finished"] = datetime.now().isoformat(timespec="seconds")
        log(f"member source ok source=cngold signals={len(signals)}")
    except Exception as exc:
        STATE["last_member_source_error"] = str(exc)
        STATE["last_member_source_finished"] = datetime.now().isoformat(timespec="seconds")
        log(f"member source failed: {exc}")


def run_scan_safely() -> None:
    if not SCAN_LOCK.acquire(blocking=False):
        return
    STATE["running"] = True
    STATE["last_scan_started"] = datetime.now().isoformat(timespec="seconds")
    STATE["last_error"] = None
    try:
        report_path, candidates, noises = run_scan(include_news=True)
        STATE["last_report"] = str(report_path)
        STATE["last_scan_finished"] = datetime.now().isoformat(timespec="seconds")
        log(f"scan ok report={report_path} candidates={len(candidates)} noises={len(noises)}")
    except Exception as exc:
        STATE["last_error"] = str(exc)
        STATE["last_scan_finished"] = datetime.now().isoformat(timespec="seconds")
        log(f"scan failed: {exc}")
    finally:
        sync_member_sources_safely()
        cleanup_timestamp_reports()
        STATE["running"] = False
        SCAN_LOCK.release()


def cleanup_timestamp_reports() -> None:
    keep_names = {"latest.html", "latest.json", "latest_zh.json"}
    try:
        for path in REPORT_DIR.iterdir():
            if not path.is_file() or path.name in keep_names:
                continue
            if re.match(r"^\d{4}-\d{2}-\d{2}_\d{4}(?:_zh)?\.(?:html|json|md)$", path.name):
                path.unlink()
    except Exception as exc:
        log(f"timestamp report cleanup failed: {exc}")


def scan_loop(interval_seconds: int) -> None:
    time.sleep(max(60, interval_seconds))
    while True:
        run_scan_safely()
        time.sleep(max(60, interval_seconds))


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def latest_important_payload() -> dict:
    if not IMPORTANT_STATE_PATH.exists():
        return {
            "模块": "北斗重要消息钉板",
            "重要消息": [],
            "说明": "暂未生成重要消息记录。",
        }
    try:
        payload = json.loads(IMPORTANT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"模块": "北斗重要消息钉板", "重要消息": [], "错误": str(exc)}
    now_utc = datetime.now(timezone.utc)
    active = []
    for record in payload.get("重要消息", []):
        expires_at = parse_iso_datetime(record.get("置顶到UTC"))
        if not expires_at:
            continue
        remaining = int((expires_at - now_utc).total_seconds())
        if remaining <= 0:
            continue
        record["置顶剩余秒"] = remaining
        active.append(record)
    active.sort(key=lambda item: (item.get("重要等级") == "强", item.get("短线发酵分数") or 0), reverse=True)
    payload["重要消息"] = active
    return payload


def latest_social_signals() -> dict:
    signals: list[dict] = []
    json_path = SOCIAL_SIGNAL_DIR / "signals.json"
    jsonl_path = SOCIAL_SIGNAL_DIR / "signals.jsonl"
    try:
        if json_path.exists():
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            raw = payload.get("社媒信号", payload if isinstance(payload, list) else [])
            signals.extend(item for item in raw if isinstance(item, dict))
        if jsonl_path.exists():
            for line in jsonl_path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception as exc:
                    log(f"social jsonl line skipped: {exc}")
                    continue
                if isinstance(item, dict):
                    signals.append(item)
    except Exception as exc:
        return {"社媒信号": [], "错误": str(exc)}
    clean: list[dict] = []
    seen: set[str] = set()
    now_utc = datetime.now(timezone.utc)
    for item in signals:
        symbol = str(item.get("股票代码") or item.get("symbol") or "").upper().strip()
        if symbol and symbol != "GOLD_BASKET" and not re.match(r"^[A-Z][A-Z0-9.]{0,9}$", symbol):
            continue
        published = parse_iso_datetime(str(item.get("发布时间") or item.get("published_at") or item.get("time") or ""))
        if published and (now_utc - published).total_seconds() > SOCIAL_MAX_AGE_SECONDS:
            continue
        key = "|".join(
            [
                symbol,
                str(item.get("平台") or item.get("platform") or ""),
                str(item.get("作者") or item.get("author") or ""),
                str(item.get("原帖链接") or item.get("url") or item.get("文字") or item.get("text") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        clean.append(item)
    return {
        "社媒信号": clean[-40:],
        "说明": "社媒用于发现热度和观点变化，已按来源和时间去重。",
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def valid_symbol(value: object) -> str:
    symbol = str(value or "").upper().strip()
    if symbol in {"", "SOURCE", "USMARKET", "USSTOCK", "MACRO"}:
        return ""
    if not re.match(r"^[A-Z][A-Z0-9.]{0,9}$", symbol):
        return ""
    return symbol


def holdings_account_payload() -> dict:
    accounts: list[str] = []
    account_overrides: dict[str, list[str]] = {}
    account_summaries: dict[str, dict] = {}
    zero_positions: list[dict] = []
    explicit_holdings: list[dict] = []
    account_error = ""

    def add_account(label: str) -> None:
        label = str(label or "").strip()
        if label and label not in accounts:
            accounts.insert(max(0, len(accounts) - 1), label)

    def add_symbol_account(symbol: str, label: str) -> None:
        symbol = str(symbol or "").upper().strip()
        label = str(label or "").strip()
        if not symbol or not label:
            return
        add_account(label)
        labels = account_overrides.setdefault(symbol, [])
        if label not in labels:
            labels.append(label)

    try:
        if HOLDINGS_ACCOUNTS_PATH.exists():
            account_payload = json.loads(HOLDINGS_ACCOUNTS_PATH.read_text(encoding="utf-8"))
            raw_accounts = account_payload.get("账户列表") or account_payload.get("accounts") or []
            if isinstance(raw_accounts, list):
                for account in raw_accounts:
                    add_account(str(account or "").strip())
            grouped = account_payload.get("账户持仓") or account_payload.get("account_holdings") or {}
            if isinstance(grouped, dict):
                for account, symbols in grouped.items():
                    label = str(account or "").strip() or "未分账户"
                    add_account(label)
                    if not isinstance(symbols, list):
                        continue
                    for symbol in symbols:
                        clean_symbol = str(symbol or "").upper().strip()
                        add_symbol_account(clean_symbol, label)
            summaries = account_payload.get("账户摘要") or account_payload.get("account_summaries") or {}
            if isinstance(summaries, dict):
                for account, summary in summaries.items():
                    label = str(account or "").strip()
                    if label and isinstance(summary, dict):
                        add_account(label)
                        account_summaries[label] = dict(summary)
            explicit_rows = account_payload.get("持仓列表") or account_payload.get("holdings") or []
            if isinstance(explicit_rows, list):
                for row in explicit_rows:
                    if not isinstance(row, dict):
                        continue
                    clean_symbol = str(row.get("股票代码") or row.get("symbol") or "").upper().strip()
                    label = str(row.get("账户") or row.get("account") or "").strip()
                    if not clean_symbol:
                        continue
                    normalized = dict(row)
                    normalized["股票代码"] = clean_symbol
                    if not label:
                        labels = account_overrides.get(clean_symbol, [])
                        label = labels[0] if len(labels) == 1 else "未分账户"
                    normalized["账户"] = label
                    add_symbol_account(clean_symbol, label)
                    explicit_holdings.append(normalized)
            raw_zero = account_payload.get("零股观察") or account_payload.get("zero_positions") or []
            if isinstance(raw_zero, list):
                zero_positions = [row for row in raw_zero if isinstance(row, dict)]
    except Exception as exc:
        account_error = str(exc)

    def account_for_symbol(symbol: str, fallback: str = "未分账户") -> str:
        labels = account_overrides.get(str(symbol or "").upper().strip(), [])
        if len(labels) == 1:
            return labels[0]
        if len(labels) > 1:
            return "、".join(labels)
        return fallback

    def build_mapping(holdings: list[dict]) -> dict[str, str]:
        mapping_lists: dict[str, list[str]] = {}
        for item in holdings:
            symbol = str(item.get("股票代码") or item.get("symbol") or "").upper().strip()
            account = str(item.get("账户") or item.get("account") or "未分账户").strip() or "未分账户"
            if not symbol:
                continue
            labels = mapping_lists.setdefault(symbol, [])
            if account not in labels:
                labels.append(account)
        return {symbol: (labels[0] if len(labels) == 1 else "、".join(labels)) for symbol, labels in mapping_lists.items()}

    explicit_symbols = {str(row.get("股票代码") or "").upper().strip() for row in explicit_holdings}
    if not WATCHLIST_CONFIG.exists():
        return {"账户列表": accounts, "持仓列表": explicit_holdings, "账户映射": build_mapping(explicit_holdings), "账户摘要": account_summaries, "零股观察": zero_positions, "账户文件": str(HOLDINGS_ACCOUNTS_PATH), "账户错误": account_error}
    in_holdings = False
    current: dict | None = None
    watchlist_holdings: list[dict] = []
    try:
        lines = WATCHLIST_CONFIG.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return {"账户列表": accounts, "持仓列表": explicit_holdings, "账户映射": build_mapping(explicit_holdings), "账户摘要": account_summaries, "零股观察": zero_positions, "错误": str(exc)}

    def flush_current() -> None:
        if not current:
            return
        symbol = str(current.get("股票代码") or "").upper().strip()
        if not symbol:
            return
        account = account_for_symbol(symbol, str(current.get("账户") or "未分账户").strip() or "未分账户")
        if symbol not in explicit_symbols:
            add_account(account)
        current["账户"] = account
        watchlist_holdings.append(dict(current))

    for raw_line in lines:
        if re.match(r"^\s{2}current_actual_holdings:\s*$", raw_line):
            flush_current()
            in_holdings = True
            current = None
            continue
        if in_holdings and re.match(r"^\s{2}[a-z_]+:\s*$", raw_line) and not raw_line.strip().startswith("current_actual_holdings"):
            flush_current()
            in_holdings = False
            current = None
            continue
        if not in_holdings:
            continue
        ticker_match = re.match(r"^\s*-\s*ticker:\s*(.+?)\s*$", raw_line)
        if ticker_match:
            flush_current()
            current = {"股票代码": ticker_match.group(1).strip().upper()}
            continue
        if current and ":" in raw_line:
            stripped = raw_line.strip()
            key, value = stripped.split(":", 1)
            value = value.strip().strip('"').strip("'")
            if key == "name":
                current["公司名称"] = value
            elif key in {"account", "broker", "source_account"}:
                current["账户"] = value
            elif key == "priority":
                current["优先级"] = value
            elif key == "mapping_symbols":
                current["映射标的"] = value
    flush_current()
    watchlist_by_symbol = {item["股票代码"]: item for item in watchlist_holdings if item.get("股票代码")}
    for row in explicit_holdings:
        symbol = str(row.get("股票代码") or "").upper().strip()
        base = watchlist_by_symbol.get(symbol, {})
        for key in ("公司名称", "优先级", "映射标的"):
            if row.get(key) in ("", None) and base.get(key) not in ("", None):
                row[key] = base[key]
    holdings = explicit_holdings + [row for row in watchlist_holdings if str(row.get("股票代码") or "").upper().strip() not in explicit_symbols]
    mapping = build_mapping(holdings)
    return {"账户列表": accounts, "持仓列表": holdings, "账户映射": mapping, "账户摘要": account_summaries, "零股观察": zero_positions, "账户文件": str(HOLDINGS_ACCOUNTS_PATH), "账户错误": account_error}


def read_latest_report_payload() -> dict:
    path = REPORT_DIR / "latest_zh.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"latest report read failed for live pulse: {exc}")
        return {}


def symbols_from_report(payload: dict) -> list[str]:
    symbols: list[str] = []
    for key in ("重要置顶", "候选股票"):
        for item in payload.get(key, []) or []:
            symbol = valid_symbol(item.get("股票代码") or item.get("symbol"))
            if symbol:
                symbols.append(symbol)
    for item in latest_social_signals().get("社媒信号", []):
        symbol = valid_symbol(item.get("股票代码") or item.get("symbol"))
        if symbol:
            symbols.append(symbol)
    return symbols


def live_seed_symbols(report_payload: dict) -> list[str]:
    symbols: list[str] = []
    symbols.extend(LIVE_CORE_SYMBOLS)
    symbols.extend(symbols_from_report(report_payload))
    try:
        _, watch_symbols, _ = relation_maps()
        symbols.extend(valid_symbol(item) for item in watch_symbols)
    except Exception as exc:
        log(f"watchlist symbols skipped for live pulse: {exc}")
    if len(symbols) < 36:
        try:
            symbols.extend(discover_yahoo_screeners(limit=10))
        except Exception as exc:
            log(f"Yahoo movers skipped for live pulse: {exc}")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in symbols:
        symbol = valid_symbol(item)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        cleaned.append(symbol)
    return cleaned[:LIVE_MAX_SYMBOLS]


def report_quote_items(report_payload: dict) -> list[dict]:
    rows: list[dict] = []
    for key in ("重要置顶", "候选股票"):
        for item in report_payload.get(key, []) or []:
            symbol = valid_symbol(item.get("股票代码"))
            quote = item.get("当前行情") or item.get("盘前行情") or {}
            if not symbol or not isinstance(quote, dict):
                continue
            rows.append(
                {
                    "股票代码": symbol,
                    "公司名称": item.get("公司名称") or symbol,
                    "当前价格": quote.get("当前价格") or quote.get("盘前价格"),
                    "当前涨跌幅": quote.get("当前涨跌幅") or quote.get("盘前涨跌幅"),
                    "当前成交量": quote.get("当前成交量") or quote.get("盘前成交量"),
                    "时段": quote.get("时段") or active_session_label(),
                    "数据源": quote.get("数据源") or "北斗最近扫描快照",
                    "关联": item.get("所属类型") or "北斗候选",
                    "来源状态": "最近快照",
                }
            )
    return rows


def relation_label(symbol: str) -> str:
    try:
        relation, _, _ = relation_maps()
        item = relation.get(symbol)
        if item:
            group = item[0]
            if group == "current_actual_holdings":
                return "实际持仓"
            if group == "watchlist":
                return "观察池"
            return group or "观察池"
    except Exception:
        pass
    if symbol in MARKET_SENTIMENT_SYMBOLS or symbol in {"SQQQ", "SOXS"}:
        return "市场ETF"
    return "市场异动"


def quote_to_live_row(symbol: str, quote, now_utc: datetime) -> dict | None:
    pct = active_change_percent(quote, now_utc)
    price = active_price(quote, now_utc)
    volume = active_volume(quote, now_utc)
    if pct is None and price is None and volume is None:
        return None
    pct_value = float(pct) if pct is not None else 0.0
    if pct is None:
        direction = "平"
    elif pct_value > 0:
        direction = "涨"
    elif pct_value < 0:
        direction = "跌"
    else:
        direction = "平"
    return {
        "股票代码": symbol,
        "公司名称": quote.name or symbol,
        "当前价格": price,
        "当前涨跌幅": pct,
        "当前成交量": volume,
        "时段": active_session_label(now_utc),
        "数据源": quote.source,
        "关联": relation_label(symbol),
        "方向": direction,
        "强度": round(min(100, abs(pct_value) * 14), 1),
        "来源状态": "实时抓取",
    }


def enrich_live_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        symbol = valid_symbol(row.get("股票代码"))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        pct = row.get("当前涨跌幅")
        try:
            pct_value = float(pct)
        except Exception:
            pct_value = 0.0
        if not row.get("方向"):
            row["方向"] = "涨" if pct_value > 0 else "跌" if pct_value < 0 else "平"
        row["强度"] = row.get("强度") or round(min(100, abs(pct_value) * 14), 1)
        row["股票代码"] = symbol
        out.append(row)
    return out


def market_temperature(rows: list[dict]) -> dict:
    sample_rows = [row for row in rows if valid_symbol(row.get("股票代码")) in MARKET_SENTIMENT_SYMBOLS]
    scope = "宽基/行业ETF市场情绪"
    if len(sample_rows) < 5:
        sample_rows = [row for row in rows if "实际持仓" not in str(row.get("关联") or "")]
        scope = "市场样本"
    if len(sample_rows) < 5:
        sample_rows = rows
        scope = "实时样本不足，使用当前快照"
    pct_values: list[float] = []
    for row in sample_rows:
        try:
            pct_values.append(float(row.get("当前涨跌幅")))
        except Exception:
            continue
    if not pct_values:
        return {"温度": 50, "标签": "等待行情", "上涨数": 0, "下跌数": 0, "平均涨跌幅": None, "样本数": 0, "口径": "等待宽基/行业ETF行情"}
    up = sum(1 for value in pct_values if value > 0)
    down = sum(1 for value in pct_values if value < 0)
    avg = sum(pct_values) / len(pct_values)
    breadth = (up - down) / max(1, len(pct_values))
    temp = int(round(clamp(50 + avg * 5 + breadth * 22, 0, 100)))
    if temp >= 70:
        label = "偏热"
    elif temp <= 35:
        label = "偏冷"
    else:
        label = "中性"
    return {
        "温度": temp,
        "标签": label,
        "上涨数": up,
        "下跌数": down,
        "平均涨跌幅": round(avg, 2),
        "样本数": len(pct_values),
        "口径": f"{scope}；5分钟刷新一次。",
    }


def live_row_by_symbol(rows: list[dict], symbol: str) -> dict | None:
    target = symbol.upper()
    for row in rows:
        if valid_symbol(row.get("股票代码")) == target:
            return row
    return None


def compact_live_row(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "股票代码": row.get("股票代码"),
        "公司名称": row.get("公司名称"),
        "当前价格": row.get("当前价格"),
        "当前涨跌幅": row.get("当前涨跌幅"),
        "当前成交量": row.get("当前成交量"),
        "时段": row.get("时段"),
        "数据源": row.get("数据源"),
        "关联": row.get("关联"),
    }


def local_koudai_quote_row(now_utc: datetime) -> dict | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    titles: list[str] = []

    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32 = ctypes.windll.user32

    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()
        if "口袋贵金属" in title:
            titles.append(title)
        return True

    try:
        user32.EnumWindows(enum_proc_type(enum_proc), 0)
    except Exception:
        return None
    for title in titles:
        match = re.search(r"(?P<price>\d+(?:\.\d+)?)\s+(?P<change>[+-]?\d+(?:\.\d+)?)\s+(?P<name>.+?)\s*\|\s*口袋贵金属", title)
        if not match:
            continue
        price = float(match.group("price"))
        change = float(match.group("change"))
        previous = price - change
        pct = (change / previous * 100) if previous else 0.0
        name = match.group("name").strip()
        return {
            "股票代码": "GOLD_BASKET",
            "公司名称": name or "口袋贵金属",
            "当前价格": round(price, 3),
            "当前涨跌幅": round(pct, 2),
            "当前成交量": None,
            "时段": "本地窗口实时",
            "数据源": "口袋贵金属窗口标题",
            "关联": "贵金属/美元风险偏好",
            "方向": "涨" if change > 0 else "跌" if change < 0 else "平",
            "强度": round(min(100, abs(pct) * 14), 1),
            "来源状态": "本机实时可见窗口",
        }
    return None


def nasdaq100_payload(rows: list[dict]) -> dict:
    qqq = live_row_by_symbol(rows, "QQQ")
    sqqq = live_row_by_symbol(rows, "SQQQ")
    return {
        "名称": "纳斯达克100",
        "显示名称": "纳斯达克100",
        "参考标的": "QQQ",
        "状态": "ok" if qqq else "等待QQQ行情",
        "当前价格": qqq.get("当前价格") if qqq else None,
        "当前涨跌幅": qqq.get("当前涨跌幅") if qqq else None,
        "当前成交量": qqq.get("当前成交量") if qqq else None,
        "时段": qqq.get("时段") if qqq else active_session_label(),
        "数据源": qqq.get("数据源") if qqq else "",
        "反向持仓": compact_live_row(sqqq),
        "说明": "使用 QQQ 实时行情观察纳斯达克100方向。",
    }


def us_index_payloads(rows: list[dict]) -> list[dict]:
    payloads: list[dict] = []
    for name, symbol in INDEX_DEFINITIONS:
        row = live_row_by_symbol(rows, symbol)
        payloads.append(
            {
                "名称": name,
                "标的": symbol,
                "状态": "ok" if row else f"等待{symbol}行情",
                "当前价格": row.get("当前价格") if row else None,
                "当前涨跌幅": row.get("当前涨跌幅") if row else None,
                "当前成交量": row.get("当前成交量") if row else None,
                "时段": row.get("时段") if row else active_session_label(),
                "数据源": row.get("数据源") if row else "",
            }
        )
    return payloads


def build_live_payload(force: bool = False) -> dict:
    now = time.time()
    if not force and isinstance(LIVE_CACHE.get("payload"), dict) and now - float(LIVE_CACHE.get("updated_at", 0)) < LIVE_TTL_SECONDS:
        return LIVE_CACHE["payload"]  # type: ignore[return-value]
    if not LIVE_LOCK.acquire(blocking=False):
        if isinstance(LIVE_CACHE.get("payload"), dict):
            return LIVE_CACHE["payload"]  # type: ignore[return-value]
        return {
            "状态": "实时行情初始化中",
            "涨幅榜": [],
            "跌幅榜": [],
            "市场温度": market_temperature([]),
            "纳斯达克100": nasdaq100_payload([]),
            "美国指数": us_index_payloads([]),
        }
    try:
        STATE["last_live_started"] = datetime.now().isoformat(timespec="seconds")
        STATE["last_live_error"] = None
        now_utc = datetime.now(timezone.utc)
        report_payload = read_latest_report_payload()
        symbols = live_seed_symbols(report_payload)
        live_rows: list[dict] = []
        source_errors: list[str] = []
        quotes = {}
        try:
            quotes.update(fetch_tradingview_quotes(symbols))
        except Exception as exc:
            source_errors.append(f"TradingView：{exc}")
        missing = [symbol for symbol in symbols if symbol not in quotes]
        if missing:
            try:
                chart_fallbacks = {symbol for symbol in missing if symbol in LIVE_CHART_FALLBACK_SYMBOLS}
                quotes.update(fetch_yahoo_quotes(missing, fallback_symbols=chart_fallbacks))
            except Exception as exc:
                source_errors.append(f"Yahoo：{exc}")
        for symbol, quote in quotes.items():
            row = quote_to_live_row(symbol, quote, now_utc)
            if row:
                live_rows.append(row)
        if len(live_rows) < 8:
            live_rows.extend(report_quote_items(report_payload))
        live_rows = enrich_live_rows(live_rows)
        missing_core = [
            symbol
            for symbol in (
                "SPY",
                "QQQ",
                "DIA",
                "IWM",
                "XLK",
                "XLF",
                "XLV",
                "SMH",
                "TLT",
                "SQQQ",
                "SOXS",
                "AAPL",
                "TSLA",
                "NVDA",
                "AMD",
                "MSFT",
                "AMZN",
                "META",
                "GOOGL",
                "NFLX",
                "PLTR",
            )
            if not live_row_by_symbol(live_rows, symbol)
        ]
        for symbol in missing_core:
            try:
                quote = fetch_yahoo_chart_quote(symbol)
            except Exception as exc:
                source_errors.append(f"Yahoo chart {symbol}：{exc}")
                continue
            row = quote_to_live_row(symbol, quote, now_utc) if quote else None
            if row:
                live_rows.append(row)
        live_rows = enrich_live_rows(live_rows)
        koudai_row = local_koudai_quote_row(now_utc)
        if koudai_row:
            live_rows = [row for row in live_rows if row.get("股票代码") != "GOLD_BASKET"]
            live_rows.append(koudai_row)
        live_rows.sort(key=lambda item: abs(float(item.get("当前涨跌幅") or 0)), reverse=True)
        gainers = sorted(live_rows, key=lambda item: float(item.get("当前涨跌幅") or 0), reverse=True)[:12]
        losers = sorted(live_rows, key=lambda item: float(item.get("当前涨跌幅") or 0))[:12]
        payload = {
            "状态": "ok",
            "生成时间UTC": now_utc.isoformat(),
            "北京时间": now_utc.astimezone().isoformat(),
            "当前美股时段": market_session(now_utc),
            "股票数量": len(live_rows),
            "市场温度": market_temperature(live_rows),
            "纳斯达克100": nasdaq100_payload(live_rows),
            "美国指数": us_index_payloads(live_rows),
            "实时快照": live_rows[:64],
            "涨幅榜": gainers,
            "跌幅榜": losers,
            "来源说明": "TradingView scanner 优先，Yahoo chart/quote 兜底；热力图5分钟刷新，覆盖宽基、行业ETF、热门科技股和异动股。",
            "来源错误": source_errors,
        }
        LIVE_CACHE["payload"] = payload
        LIVE_CACHE["updated_at"] = time.time()
        STATE["last_live_count"] = len(live_rows)
        STATE["last_live_finished"] = datetime.now().isoformat(timespec="seconds")
        if source_errors:
            STATE["last_live_error"] = "；".join(source_errors[:2])
        return payload
    except Exception as exc:
        STATE["last_live_error"] = str(exc)
        STATE["last_live_finished"] = datetime.now().isoformat(timespec="seconds")
        log(f"live pulse failed: {exc}")
        if isinstance(LIVE_CACHE.get("payload"), dict):
            payload = dict(LIVE_CACHE["payload"])  # type: ignore[arg-type]
            payload["状态"] = "最近快照"
            payload["来源错误"] = [str(exc)]
            return payload
        return {
            "状态": "读取失败",
            "错误": str(exc),
            "涨幅榜": [],
            "跌幅榜": [],
            "市场温度": market_temperature([]),
            "纳斯达克100": nasdaq100_payload([]),
            "美国指数": us_index_payloads([]),
        }
    finally:
        LIVE_LOCK.release()


def latest_payload() -> dict:
    path = REPORT_DIR / "latest_zh.json"
    if not path.exists():
        return {
            "状态": "暂无报告",
            "提示": "后台还没有生成 latest_zh.json，可以点击页面上的立即刷新。",
            "服务状态": {**STATE, "scan_enabled": SCAN_ENABLED},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"状态": "读取失败", "错误": str(exc), "服务状态": {**STATE, "scan_enabled": SCAN_ENABLED}}
    important = latest_important_payload()
    social = latest_social_signals()
    payload["重要置顶"] = important.get("重要消息", [])
    payload["重要记录状态"] = {
        "说明": important.get("说明"),
        "历史JSONL": important.get("历史JSONL"),
        "当天Markdown": important.get("当天Markdown"),
        "数量": len(important.get("重要消息", [])),
    }
    payload["社媒信号"] = social.get("社媒信号", [])
    payload["社媒说明"] = social.get("说明")
    payload["持仓账户"] = holdings_account_payload()
    payload["服务状态"] = {**STATE, "scan_enabled": SCAN_ENABLED}
    if build_data_source_layer_payload is not None:
        payload["数据源层V1"] = build_data_source_layer_payload(payload, payload.get("社媒信号", []))
        payload["北斗事件流V1"] = payload["数据源层V1"].get("事件流", [])
    else:
        payload["数据源层V1"] = {"状态": "不可用", "错误": BEIDOU_SOURCE_LAYER_ERROR}
        payload["北斗事件流V1"] = []
    return payload


def dashboard_html() -> bytes:
    if DASHBOARD_TEMPLATE.exists():
        try:
            return DASHBOARD_TEMPLATE.read_bytes()
        except Exception as exc:
            log(f"dashboard template read failed: {exc}")
    return DASHBOARD_HTML.encode("utf-8")


DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>北斗美股全时段异动雷达</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #061014;
      --panel: #0d1b20;
      --panel2: #10242b;
      --text: #ecf7f4;
      --muted: #9db5b0;
      --line: #23424a;
      --accent: #32d6a6;
      --warn: #f7c948;
      --bad: #ff6b6b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
      line-height: 1.55;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 5;
      background: rgba(6,16,20,.95);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }
    .wrap { width: min(1120px, calc(100% - 28px)); margin: 0 auto; }
    .top {
      min-height: 86px;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 14px 0;
    }
    .topLeft {
      display: flex;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }
    .autoPanel {
      min-width: 150px;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 9px 11px;
    }
    .autoRow {
      display: flex;
      align-items: center;
      gap: 7px;
      margin-top: 3px;
      font-size: 13px;
    }
    .autoDot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 3px rgba(50,216,166,.12);
      flex: 0 0 auto;
    }
    .actions { display: flex; gap: 8px; align-items: center; }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel2);
      color: var(--text);
      border-radius: 6px;
      padding: 10px 13px;
      cursor: pointer;
      font-size: 14px;
    }
    button:hover { border-color: var(--accent); }
    main { padding: 18px 0 36px; }
    .status {
      display: grid;
      grid-template-columns: repeat(5, minmax(0,1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .box {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 12px;
    }
    .label { color: var(--muted); font-size: 12px; }
    .value { margin-top: 4px; font-size: 15px; overflow-wrap: anywhere; }
    .summary {
      white-space: pre-wrap;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 14px;
      overflow-wrap: anywhere;
    }
    .sectionHead {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin: 18px 0 10px;
    }
    .sectionHead h2 {
      margin: 0;
      font-size: 18px;
    }
    .sectionHead span {
      color: var(--muted);
      font-size: 13px;
    }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
    .importantGrid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; margin-bottom: 14px; }
    .card {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
    }
    .importantCard {
      border-color: rgba(247,201,72,.65);
      background: linear-gradient(180deg, rgba(247,201,72,.10), rgba(13,27,32,1));
    }
    .card h2 { margin: 0 0 8px; font-size: 18px; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 10px; }
    .chip {
      border: 1px solid var(--line);
      background: #0b171c;
      color: var(--muted);
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 12px;
    }
    .score { color: var(--accent); font-weight: 700; }
    .risk { color: var(--warn); }
    .bad { color: var(--bad); }
    .timer { color: var(--warn); font-weight: 700; }
    .muted { color: var(--muted); }
    .checks { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }
    .check { margin: 6px 0; color: var(--muted); font-size: 13px; }
    .check strong { color: var(--text); }
    @media (max-width: 760px) {
      .top { align-items: flex-start; flex-direction: column; }
      .topLeft { align-items: flex-start; flex-direction: column; width: 100%; }
      .autoPanel { width: 100%; }
      .status, .grid, .importantGrid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <div class="topLeft">
        <div class="autoPanel">
          <div class="label">自动刷新</div>
          <div class="autoRow"><span class="autoDot"></span><span>已开启</span></div>
          <div class="sub" id="refreshCountdown">30秒后读取最新结果</div>
        </div>
        <div>
          <h1>北斗美股全时段异动雷达</h1>
          <div class="sub">自动刷新北斗信息源</div>
        </div>
      </div>
      <div class="actions"><button id="scanBtn">立即刷新</button></div>
    </div>
  </header>
  <main class="wrap">
    <section class="status">
      <div class="box"><div class="label">北京时间</div><div class="value" id="bj">-</div></div>
      <div class="box"><div class="label">美东时间</div><div class="value" id="et">-</div></div>
      <div class="box"><div class="label">美股时段</div><div class="value" id="session">-</div></div>
      <div class="box"><div class="label">后台状态</div><div class="value" id="state">-</div></div>
      <div class="box"><div class="label">自动刷新</div><div class="value">页面 30 秒 / 扫描约 3 分钟</div></div>
      <div class="box"><div class="label">重要置顶</div><div class="value" id="importantCount">-</div></div>
    </section>
    <section class="summary" id="summary">正在读取北斗雷达...</section>
    <div class="sectionHead">
      <h2>重要置顶</h2>
      <span>重要消息约保留15分钟，错过可看本地重要记录</span>
    </div>
    <section class="importantGrid" id="important"></section>
    <div class="sectionHead">
      <h2>实时候选</h2>
      <span>随最新扫描刷新</span>
    </div>
    <section class="grid" id="cards"></section>
  </main>
  <script>
    const POLL_SECONDS = 30;
    let nextLoadAt = Date.now() + POLL_SECONDS * 1000;
    const q = (id) => document.getElementById(id);
    function fmt(v) {
      if (v === null || v === undefined || v === '') return '未知';
      if (typeof v === 'number') return Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : v.toFixed(2);
      return String(v);
    }
    function priceFmt(v) {
      if (v === null || v === undefined || v === '') return '价格未知';
      return '$' + Number(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }
    function pctZh(v) {
      if (v === null || v === undefined || v === '') return '涨跌未知';
      const n = Number(v);
      return `${n >= 0 ? '涨' : '跌'}${Math.abs(n).toFixed(2)}%`;
    }
    function itemQuote(item) {
      return item['当前行情'] || item['盘前行情'] || {};
    }
    function quoteBrief(quote) {
      const label = quote['时段'] || '当前';
      const price = quote['当前价格'] ?? quote['盘前价格'];
      const pct = quote['当前涨跌幅'] ?? quote['盘前涨跌幅'];
      return `${label} ${priceFmt(price)} ｜ ${pctZh(pct)}`;
    }
    function firstLines(text, max=8) {
      return String(text || '').split('\\n').slice(0, max).join('\\n');
    }
    function renderCheck(checks) {
      if (!checks) return '';
      return Object.entries(checks).map(([name, item]) => {
        const status = item['状态'] || '未知';
        const summary = item['摘要'] || '';
        return `<div class="check"><strong>${name}</strong>：${status}；${summary}</div>`;
      }).join('');
    }
    function minutesLeft(seconds) {
      const v = Number(seconds || 0);
      if (v <= 0) return '即将移除';
      return Math.ceil(v / 60) + '分钟';
    }
    function firstCatalyst(item) {
      const cats = item['催化来源'] || [];
      return cats[0] || {};
    }
    function timeBrief(item) {
      if (item['时间标注']) return item['时间标注'];
      const cat = firstCatalyst(item);
      const raw = cat['发布时间'];
      if (!raw) return '消息时间待确认';
      const dt = new Date(raw);
      if (Number.isNaN(dt.getTime())) return '消息时间待确认';
      const now = new Date();
      const diff = Math.max(0, Math.floor((now - dt) / 1000));
      let rel = '刚刚';
      if (diff >= 86400) rel = `约${Math.floor(diff / 86400)}天前`;
      else if (diff >= 3600) rel = `约${Math.floor(diff / 3600)}小时前`;
      else if (diff >= 60) rel = `约${Math.floor(diff / 60)}分钟前`;
      const bj = dt.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
      const et = dt.toLocaleString('zh-CN', { timeZone: 'America/New_York', hour12: false });
      const fresh = cat['是否新消息'] ? '新消息' : '旧消息新发酵';
      return `消息时间：北京时间 ${bj} / 美东 ${et} / ${rel} / ${fresh}`;
    }
    function renderImportant(list) {
      const box = q('important');
      q('importantCount').textContent = `${list.length} 条`;
      if (!list.length) {
        box.innerHTML = '<div class="card muted">暂无置顶重要消息。普通候选仍在下方实时刷新。</div>';
        return;
      }
      box.innerHTML = list.map(item => {
        const quote = itemQuote(item);
        const cat = firstCatalyst(item);
        const risks = item['风险标签'] || [];
        return `<article class="card importantCard">
          <h2>${item['股票代码']} / ${item['公司名称']} ｜ ${quoteBrief(quote)}</h2>
          <div class="chips">
            <span class="chip score">${item['短线发酵分数']}/100</span>
            <span class="chip">${item['所属类型']}</span>
            <span class="chip timer">剩余${minutesLeft(item['置顶剩余秒'])}</span>
          </div>
          <div>置顶原因：${item['置顶原因'] || '重要消息'}</div>
          <div>事件标注：${item['事件标注'] || '待标注'}</div>
          <div>时间标注：${timeBrief(item)}</div>
          <div>量：${fmt(quote['当前成交量'] ?? quote['盘前成交量'])}</div>
          <div>事件：${cat['中文标题'] || cat['标题'] || '暂无明确催化'}｜${cat['来源'] || '来源待确认'}</div>
          <div class="${risks.length ? 'risk' : ''}">风险：${risks[0] || '当前时段波动和价差风险，需人工确认'}</div>
        </article>`;
      }).join('');
    }
    function render(data) {
      q('bj').textContent = data['北京时间'] || '-';
      q('et').textContent = data['美东时间'] || '-';
      const session = data['当前美股时段'] || {};
      q('session').textContent = session.label ? `${session.label}${session.note ? ' / ' + session.note : ''}` : '-';
      const svc = data['服务状态'] || {};
      q('state').textContent = svc.running ? '扫描中' : (svc.last_error ? '最近有错误' : '待命');
      q('summary').textContent = firstLines(data['中文报告'] || data['提示'] || '暂无报告', 12);
      renderImportant(data['重要置顶'] || []);
      const cards = q('cards');
      const list = data['候选股票'] || [];
      if (!list.length) {
        cards.innerHTML = '<div class="card">暂无候选。若现在不是美股交易时段，这是正常现象。</div>';
        return;
      }
      cards.innerHTML = list.map(item => {
        const quote = itemQuote(item);
        const cats = item['催化来源'] || [];
        const risks = item['风险标签'] || [];
        return `<article class="card">
          <h2>${item['股票代码']} / ${item['公司名称']} ｜ ${quoteBrief(quote)}</h2>
          <div class="chips">
            <span class="chip">${item['所属类型']}</span>
            <span class="chip score">${item['短线发酵分数']}/100</span>
            <span class="chip">${item['信息处理标签']}</span>
          </div>
          <div>量：${fmt(quote['当前成交量'] ?? quote['盘前成交量'])}｜源：${quote['数据源'] || '未知'}</div>
          <div>事件标注：${item['事件标注'] || '待标注'}</div>
          <div>时间标注：${timeBrief(item)}</div>
          <div>催化：${cats[0] ? `${cats[0]['催化类型']}｜${cats[0]['来源']}｜${cats[0]['中文标题'] || cats[0]['标题']}` : '暂无明确催化'}</div>
          <div class="${risks.length ? 'risk' : ''}">风险：${risks[0] || '当前时段波动和价差风险，需人工确认'}</div>
          <div class="checks">${renderCheck(item['五站交叉验证'])}</div>
        </article>`;
      }).join('');
    }
    async function load() {
      try {
        const res = await fetch('/api/latest?ts=' + Date.now());
        render(await res.json());
        nextLoadAt = Date.now() + POLL_SECONDS * 1000;
      } catch (err) {
        q('summary').textContent = '读取失败：' + err;
        nextLoadAt = Date.now() + POLL_SECONDS * 1000;
      }
    }
    function tickCountdown() {
      const left = Math.max(0, Math.ceil((nextLoadAt - Date.now()) / 1000));
      q('refreshCountdown').textContent = `${left}秒后读取最新结果`;
    }
    q('scanBtn').addEventListener('click', async () => {
      q('state').textContent = '已请求刷新';
      await fetch('/api/scan', {method: 'POST'});
      setTimeout(load, 1200);
    });
    load();
    setInterval(load, POLL_SECONDS * 1000);
    setInterval(tickCountdown, 1000);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, dashboard_html(), "text/html; charset=utf-8")
            return
        if path == "/api/latest":
            self._send(
                200,
                json.dumps(latest_payload(), ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return
        if path == "/api/status":
            self._send(
                200,
                json.dumps(STATE, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return
        if path == "/api/live":
            force = "force=1" in self.path or "force=true" in self.path
            self._send(
                200,
                json.dumps(build_live_payload(force=force), ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return
        if path == "/api/important":
            self._send(
                200,
                json.dumps(latest_important_payload(), ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return
        if path.startswith("/social-media/"):
            rel = unquote(path[len("/social-media/") :]).replace("\\", "/")
            target = (SOCIAL_MEDIA_DIR / rel).resolve()
            try:
                if not str(target).startswith(str(SOCIAL_MEDIA_DIR.resolve())):
                    self._send(403, b"forbidden", "text/plain; charset=utf-8")
                    return
                if not target.exists() or target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                    return
                mime = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                }[target.suffix.lower()]
                self._send(200, target.read_bytes(), mime)
            except Exception as exc:
                self._send(500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/scan":
            if not SCAN_ENABLED:
                self._send(
                    409,
                    json.dumps({"状态": "扫描已在稳定看板模式下关闭", "服务状态": STATE}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            threading.Thread(target=run_scan_safely, daemon=True).start()
            self._send(
                202,
                json.dumps({"状态": "已触发刷新", "服务状态": STATE}, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        log(fmt % args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local 北斗 radar dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=int, default=180, help="Background scan interval in seconds")
    parser.add_argument("--scan-now", action="store_true", help="Run one scan before serving")
    parser.add_argument("--disable-scan", action="store_true", help="Serve existing latest files without starting scan jobs")
    args = parser.parse_args(argv)

    global SCAN_ENABLED
    SCAN_ENABLED = not args.disable_scan
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if SCAN_ENABLED and (args.scan_now or not (REPORT_DIR / "latest_zh.json").exists()):
        threading.Thread(target=run_scan_safely, daemon=True).start()
    if SCAN_ENABLED and args.interval > 0:
        threading.Thread(target=scan_loop, args=(args.interval,), daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"北斗雷达看板已启动：http://{args.host}:{args.port}")
    log(f"dashboard serving http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
