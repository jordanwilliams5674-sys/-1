#!/usr/bin/env python3
"""Beidou full-session US stock mover radar.

This is not an auto-trading system. It does not place orders, does not promise
profit, and only creates a research alert for manual review.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from news_catalyst_scan import Catalyst, catalysts_for_ticker, parse_watchlist_config  # noqa: E402
from cross_verify import SourceCheck, five_site_cross_check, format_cross_checks, fetch_tradingview_scan  # noqa: E402
from nasdaq100_universe import get_nasdaq100_symbols  # noqa: E402

try:
    from send_alert import send_alert  # noqa: E402
except Exception:  # pragma: no cover - notification fallback
    send_alert = None

REPORT_DIR = ROOT / "reports" / "premarket"
IMPORTANT_DIR = REPORT_DIR / "important"
LOG_DIR = ROOT / "logs"
CONFIG_PATH = ROOT / "config" / "watchlist.yaml"
USER_AGENT = "premarket_mover_radar/1.0 contact=295765031@qq.com"
IMPORTANT_PIN_MINUTES = 90
IMPORTANT_ACTIVE_LIMIT = 24
TRANSLATION_CACHE_PATH = LOG_DIR / "translation_cache.json"
TRANSLATION_CACHE: dict[str, str] | None = None
SECRETS_ENV_PATH = ROOT / "config" / "secrets.env"


def load_local_env(path: Path = SECRETS_ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


load_local_env()

HIGH_RISK_WORDS = [
    "public offering",
    "registered direct",
    "securities offering",
    "share offering",
    "stock offering",
    "atm offering",
    "dilution",
    "bankruptcy",
    "chapter 11",
    "delisting",
    "reverse split",
    "going concern",
    "lawsuit",
    "investigation",
    "misses",
]

THEME_WORDS = [
    "ai",
    "artificial intelligence",
    "data center",
    "semiconductor",
    "hbm",
    "dram",
    "memory",
    "networking",
    "cpo",
    "optical",
    "nuclear",
    "smr",
    "defense",
    "drone",
    "robot",
    "quantum",
    "stablecoin",
    "crypto",
    "solar",
    "tariff",
    "cybersecurity",
    "fed",
    "rate",
    "dollar",
    "gold",
    "treasury",
]

EXACT_EVENT_TRANSLATIONS = {
    "gary black says broadcom, marvell are 'big winners' as focus shifts to custom ai chips as nvidia ceo jensen huang touts 'next trillion-dollar company'":
        "Gary Black 表示，市场关注点转向定制 AI 芯片后，Broadcom 和 Marvell 是明显受益者；Nvidia CEO 黄仁勋提到“下一家万亿美元公司”。",
    "rigetti gains from potential $100 million u.s. quantum r&d backing":
        "Rigetti 因潜在 1 亿美元美国量子研发支持消息受到关注。",
    "agentic ai has holes. circle and nium are trying to fill them":
        "Circle 与 Nium 试图补足智能体 AI 支付环节的缺口。",
    "gold etfs shine again as ceasefire hopes lift market optimism":
        "停火希望提振市场情绪，黄金 ETF 再度走强。",
    "tesla faces china fsd lawsuit as robotics and valuation risks grow":
        "Tesla 在中国面临 FSD 相关诉讼，同时机器人业务和估值风险升温。",
    "micron (mu) rises higher than market: key facts":
        "Micron 跑赢大盘上涨，市场关注其近期关键基本面和价格表现。",
    "oracle reshapes ai data centers with clean power and arm shift":
        "Oracle 围绕清洁电力和 Arm 架构调整 AI 数据中心布局。",
    "smr stock gains overnight: nuclear momentum returns as regulatory veteran joins board":
        "NuScale 盘前受到关注：核电题材热度回升，公司董事会新增监管领域资深人士。",
    "ouster shares more than double ytd: is it still worth buying?":
        "Ouster 年内股价已翻倍以上，市场讨论其上涨后是否仍有吸引力。",
    "the coca-cola company readies listing of india bottler":
        "可口可乐准备推进印度装瓶业务上市。",
    "berkshire hathaway got a sweet deal on alphabet stock":
        "市场文章提到 Berkshire Hathaway 对 Alphabet 的投资交易，需确认与可口可乐是否直接相关。",
}


@dataclass
class Quote:
    symbol: str
    name: str = ""
    price: float | None = None
    regular_change_percent: float | None = None
    overnight_price: float | None = None
    overnight_change_percent: float | None = None
    overnight_volume: int | None = None
    premarket_price: float | None = None
    premarket_change_percent: float | None = None
    premarket_volume: int | None = None
    postmarket_price: float | None = None
    postmarket_change_percent: float | None = None
    postmarket_volume: int | None = None
    regular_volume: int | None = None
    bid: float | None = None
    ask: float | None = None
    day_high: float | None = None
    source: str = "Yahoo Finance quote API"
    raw: dict = field(default_factory=dict)


@dataclass
class Candidate:
    symbol: str
    company_name: str
    quote: Quote
    catalysts: list[Catalyst]
    relation: str
    group: str
    score: int
    score_parts: dict
    risk_flags: list[str]
    operation_label: str
    alert_level: str
    cross_checks: dict[str, SourceCheck] = field(default_factory=dict)
    is_noise: bool = False
    noise_reason: str = ""


def market_session(now_utc: datetime | None = None) -> dict[str, str | bool]:
    now_utc = now_utc or datetime.now(timezone.utc)
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    minutes = et.hour * 60 + et.minute
    weekday = et.weekday()
    is_weekday = weekday < 5
    is_overnight = (
        (weekday in {0, 1, 2, 3, 4} and minutes < 4 * 60)
        or (weekday in {0, 1, 2, 3} and minutes >= 20 * 60)
        or (weekday == 6 and minutes >= 20 * 60)
    )
    if is_overnight:
        key, label, note = "overnight", "夜盘", "美东20:00-04:00"
        has_live_price_source = False
        price_note = "当前公开免费源对夜盘实时成交支持不稳定；若无夜盘专用字段，则回退到最后可得盘后价，仅作线索。"
    elif is_weekday and 4 * 60 <= minutes < 9 * 60 + 30:
        key, label, note = "premarket", "盘前", "美东04:00-09:30"
        has_live_price_source = True
        price_note = "优先使用盘前价格和盘前成交量。"
    elif is_weekday and 9 * 60 + 30 <= minutes < 16 * 60:
        key, label, note = "regular", "盘中", "美东09:30-16:00"
        has_live_price_source = True
        price_note = "优先使用常规交易时段价格和成交量。"
    elif is_weekday and 16 * 60 <= minutes < 20 * 60:
        key, label, note = "postmarket", "盘后", "美东16:00-20:00"
        has_live_price_source = True
        price_note = "优先使用盘后价格和盘后成交量。"
    else:
        key, label, note = "closed", "非交易时段", "保留新闻/SEC线索，等待下一交易时段量价确认"
        has_live_price_source = False
        price_note = "当前不做实时量价确认，只保留新闻和事件线索。"
    return {
        "key": key,
        "label": label,
        "note": note,
        "is_live_market": key in {"premarket", "regular", "postmarket"},
        "has_live_price_source": has_live_price_source,
        "price_note": price_note,
    }


def active_price(q: Quote, now_utc: datetime | None = None) -> float | None:
    key = str(market_session(now_utc)["key"])
    if key == "overnight":
        for value in (q.overnight_price, q.postmarket_price, q.price, q.premarket_price):
            if value is not None:
                return value
        return None
    if key == "premarket":
        return q.premarket_price if q.premarket_price is not None else q.price
    if key == "regular":
        return q.price if q.price is not None else q.premarket_price
    if key == "postmarket":
        return q.postmarket_price if q.postmarket_price is not None else q.price
    for value in (q.postmarket_price, q.premarket_price, q.price):
        if value is not None:
            return value
    return None


def active_change_percent(q: Quote, now_utc: datetime | None = None) -> float | None:
    key = str(market_session(now_utc)["key"])
    if key == "overnight":
        for value in (q.overnight_change_percent, q.postmarket_change_percent, q.regular_change_percent, q.premarket_change_percent):
            if value is not None:
                return value
        return None
    if key == "premarket":
        return q.premarket_change_percent if q.premarket_change_percent is not None else q.regular_change_percent
    if key == "regular":
        return q.regular_change_percent if q.regular_change_percent is not None else q.premarket_change_percent
    if key == "postmarket":
        return q.postmarket_change_percent if q.postmarket_change_percent is not None else q.regular_change_percent
    for value in (q.postmarket_change_percent, q.premarket_change_percent, q.regular_change_percent):
        if value is not None:
            return value
    return None


def active_volume(q: Quote, now_utc: datetime | None = None) -> int | None:
    key = str(market_session(now_utc)["key"])
    if key == "overnight":
        for value in (q.overnight_volume, q.postmarket_volume, q.regular_volume, q.premarket_volume):
            if value is not None:
                return value
        return None
    if key == "premarket":
        return q.premarket_volume
    if key == "regular":
        return q.regular_volume
    if key == "postmarket":
        return q.postmarket_volume if q.postmarket_volume is not None else q.regular_volume
    for value in (q.postmarket_volume, q.premarket_volume, q.regular_volume):
        if value is not None:
            return value
    return None


def active_session_label(now_utc: datetime | None = None) -> str:
    return str(market_session(now_utc)["label"])


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (LOG_DIR / "premarket_scan.log").open("a", encoding="utf-8") as fh:
        fh.write(f"[{ts}] {message}\n")


def http_get(url: str, timeout: int = 20, headers: dict | None = None) -> str:
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Referer": "https://finance.yahoo.com/",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_json(url: str, timeout: int = 20, headers: dict | None = None) -> dict:
    return json.loads(http_get(url, timeout=timeout, headers=headers))


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        if math.isnan(result):
            return None
        return result
    except Exception:
        return None


def safe_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def discover_yahoo_screeners(limit: int = 50) -> list[str]:
    """Use Yahoo predefined screeners as broad-market seeds.

    These are not premarket-only screeners. The candidates still need
    current-session price/volume confirmation before they survive scoring.
    """
    symbols: list[str] = []
    screeners = ["day_gainers", "day_losers", "most_actives"]
    for screener in screeners:
        url = (
            "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?"
            + urllib.parse.urlencode({"scrIds": screener, "count": 25})
        )
        try:
            data = http_json(url, timeout=8)
        except Exception as exc:
            log(f"Yahoo screener {screener} skipped: {exc}")
            continue
        rows = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
        for row in rows:
            symbol = row.get("symbol")
            if symbol and re.match(r"^[A-Z][A-Z0-9.]{0,9}$", symbol):
                symbols.append(symbol)
        if len(symbols) >= limit:
            break
    return list(dict.fromkeys(symbols))[:limit]


def discover_polygon_movers() -> list[str]:
    key = os.environ.get("POLYGON_API_KEY") or os.environ.get("MASSIVE_API_KEY")
    if not key:
        return []
    urls = [
        f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers?apiKey={urllib.parse.quote(key)}",
        f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/losers?apiKey={urllib.parse.quote(key)}",
    ]
    symbols: list[str] = []
    for url in urls:
        try:
            data = http_json(url, timeout=10)
        except Exception as exc:
            log(f"Polygon/Massive movers skipped: {exc}")
            continue
        for row in data.get("tickers", []):
            ticker = row.get("ticker")
            if ticker:
                symbols.append(ticker)
    return list(dict.fromkeys(symbols))[:80]


def fetch_yahoo_quotes(symbols: list[str], fallback_symbols: set[str] | None = None) -> dict[str, Quote]:
    quotes: dict[str, Quote] = {}
    fallback_symbols = fallback_symbols or set()
    clean = [s for s in symbols if s and s != "GOLD_BASKET"]
    for batch in chunks(clean, 50):
        url = "https://query1.finance.yahoo.com/v7/finance/quote?" + urllib.parse.urlencode({"symbols": ",".join(batch)})
        try:
            data = http_json(url, timeout=10)
        except Exception as exc:
            log(f"Yahoo quote batch skipped ({','.join(batch[:5])}...): {exc}")
            for symbol in batch:
                if symbol.upper() not in fallback_symbols:
                    continue
                chart_quote = fetch_yahoo_chart_quote(symbol)
                if chart_quote:
                    quotes[chart_quote.symbol] = chart_quote
            continue
        for row in data.get("quoteResponse", {}).get("result", []):
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            quote = Quote(
                symbol=symbol,
                name=row.get("shortName") or row.get("longName") or symbol,
                price=safe_float(row.get("regularMarketPrice")),
                regular_change_percent=safe_float(row.get("regularMarketChangePercent")),
                overnight_price=safe_float(row.get("postMarketPrice")),
                overnight_change_percent=safe_float(row.get("postMarketChangePercent")),
                overnight_volume=safe_int(row.get("postMarketVolume")),
                premarket_price=safe_float(row.get("preMarketPrice")),
                premarket_change_percent=safe_float(row.get("preMarketChangePercent")),
                premarket_volume=safe_int(row.get("preMarketVolume")),
                postmarket_price=safe_float(row.get("postMarketPrice")),
                postmarket_change_percent=safe_float(row.get("postMarketChangePercent")),
                postmarket_volume=safe_int(row.get("postMarketVolume")),
                regular_volume=safe_int(row.get("regularMarketVolume")),
                bid=safe_float(row.get("bid")),
                ask=safe_float(row.get("ask")),
                day_high=safe_float(row.get("regularMarketDayHigh")),
                raw=row,
            )
            quotes[symbol] = quote
    return quotes


def fetch_tradingview_quotes(symbols: list[str]) -> dict[str, Quote]:
    quotes: dict[str, Quote] = {}
    try:
        rows = fetch_tradingview_scan([s for s in symbols if s != "GOLD_BASKET"])
    except Exception as exc:
        log(f"TradingView scanner skipped: {exc}")
        return quotes
    for symbol, row in rows.items():
        pm_change = safe_float(row.get("premarket_change"))
        pm_volume = safe_int(row.get("premarket_volume"))
        regular_change = safe_float(row.get("change"))
        regular_volume = safe_int(row.get("volume"))
        close_price = safe_float(row.get("close"))
        quote = Quote(
            symbol=symbol.upper(),
            name=row.get("description") or symbol.upper(),
            price=close_price,
            regular_change_percent=regular_change,
            premarket_price=close_price,
            premarket_change_percent=pm_change,
            premarket_volume=pm_volume,
            regular_volume=regular_volume,
            source="TradingView scanner",
            raw=row,
        )
        quotes[quote.symbol] = quote
    return quotes


def fetch_yahoo_chart_quote(symbol: str) -> Quote | None:
    """Fallback quote from Yahoo chart endpoint.

    The quote endpoint can require a crumb/cookie. The chart endpoint is often
    accessible and includes pre/post 1-minute bars, so it can estimate the
    current live-session price, percentage change, and volume.
    """
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?" + urllib.parse.urlencode(
        {"interval": "1m", "range": "1d", "includePrePost": "true"}
    )
    try:
        data = http_json(url, timeout=7)
    except Exception as exc:
        log(f"Yahoo chart fallback skipped for {symbol}: {exc}")
        return None

    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {})
    timestamps = result.get("timestamp") or []
    quote_rows = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote_rows.get("close") or []
    volumes = quote_rows.get("volume") or []
    highs = quote_rows.get("high") or []
    previous = safe_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
    regular_price = safe_float(meta.get("regularMarketPrice"))
    exchange_tz = ZoneInfo(meta.get("exchangeTimezoneName") or "America/New_York")

    latest_price = regular_price
    overnight_price = None
    overnight_volume = 0
    premarket_price = None
    premarket_volume = 0
    regular_intraday_price = regular_price
    regular_intraday_volume = 0
    postmarket_price = None
    postmarket_volume = 0
    now_et = datetime.now(exchange_tz)
    session_date = now_et.date()
    overnight_start_date = session_date if now_et.hour >= 20 else session_date - timedelta(days=1)
    overnight_end_date = overnight_start_date + timedelta(days=1)

    for ts, close, vol in zip(timestamps, closes, volumes):
        if close is None:
            continue
        dt = datetime.fromtimestamp(ts, exchange_tz)
        minutes = dt.hour * 60 + dt.minute
        if (
            (dt.date() == overnight_start_date and minutes >= 20 * 60)
            or (dt.date() == overnight_end_date and minutes < 4 * 60)
        ):
            overnight_price = safe_float(close)
            overnight_volume += int(vol or 0)
        if dt.date() != session_date:
            latest_price = safe_float(close) or latest_price
            continue
        if 4 * 60 <= minutes < 9 * 60 + 30:
            premarket_price = safe_float(close)
            premarket_volume += int(vol or 0)
        elif 9 * 60 + 30 <= minutes < 16 * 60:
            regular_intraday_price = safe_float(close)
            regular_intraday_volume += int(vol or 0)
        elif 16 * 60 <= minutes < 20 * 60:
            postmarket_price = safe_float(close)
            postmarket_volume += int(vol or 0)
        latest_price = safe_float(close) or latest_price

    overnight_pct = None
    premarket_pct = None
    regular_pct = None
    postmarket_pct = None
    if overnight_price is not None and previous:
        overnight_pct = (overnight_price - previous) / previous * 100
    if premarket_price is not None and previous:
        premarket_pct = (premarket_price - previous) / previous * 100
    if regular_intraday_price is not None and previous:
        regular_pct = (regular_intraday_price - previous) / previous * 100
    if postmarket_price is not None and previous:
        postmarket_pct = (postmarket_price - previous) / previous * 100

    day_high = None
    numeric_highs = [safe_float(h) for h in highs if h is not None]
    numeric_highs = [h for h in numeric_highs if h is not None]
    if numeric_highs:
        day_high = max(numeric_highs)

    return Quote(
        symbol=symbol.upper(),
        name=symbol.upper(),
        price=latest_price,
        regular_change_percent=regular_pct,
        overnight_price=overnight_price,
        overnight_change_percent=overnight_pct,
        overnight_volume=overnight_volume if overnight_volume else None,
        premarket_price=premarket_price,
        premarket_change_percent=premarket_pct,
        premarket_volume=premarket_volume if premarket_volume else None,
        postmarket_price=postmarket_price,
        postmarket_change_percent=postmarket_pct,
        postmarket_volume=postmarket_volume if postmarket_volume else None,
        regular_volume=safe_int(meta.get("regularMarketVolume")) or (regular_intraday_volume if regular_intraday_volume else None),
        day_high=day_high,
        source="Yahoo Finance chart fallback",
        raw={"meta": meta},
    )


def fetch_finnhub_quote(symbol: str) -> Quote | None:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    url = "https://finnhub.io/api/v1/quote?" + urllib.parse.urlencode({"symbol": symbol, "token": key})
    try:
        data = http_json(url, timeout=8)
    except Exception as exc:
        log(f"Finnhub quote skipped for {symbol}: {exc}")
        return None
    current = safe_float(data.get("c"))
    previous = safe_float(data.get("pc"))
    pct = ((current - previous) / previous * 100) if current and previous else None
    return Quote(
        symbol=symbol,
        name=symbol,
        price=current,
        regular_change_percent=pct,
        overnight_price=current,
        overnight_change_percent=pct,
        premarket_price=current,
        premarket_change_percent=pct,
        source="Finnhub quote API",
        raw=data,
    )


def relation_maps():
    items, meta = parse_watchlist_config(CONFIG_PATH)
    relation: dict[str, tuple[str, str, str, list[str]]] = {}
    quote_symbols: list[str] = []
    for item in items:
        relation[item.ticker] = (item.group, item.name or item.ticker, item.priority, item.mapping_symbols)
        if not item.quote_enabled:
            continue
        if item.ticker == "GOLD_BASKET":
            for mapped in item.mapping_symbols:
                relation[mapped.upper()] = (item.group, f"黄金/积存金映射：{mapped}", item.priority, [])
                quote_symbols.append(mapped)
        else:
            quote_symbols.append(item.ticker)
    return relation, quote_symbols, meta


def spread_percent(q: Quote) -> float | None:
    if not q.bid or not q.ask or q.bid <= 0 or q.ask <= 0:
        return None
    mid = (q.bid + q.ask) / 2
    return (q.ask - q.bid) / mid * 100 if mid else None


def risk_flags_for(q: Quote, catalysts: list[Catalyst]) -> list[str]:
    flags: list[str] = []
    pct = active_change_percent(q)
    vol = active_volume(q) or 0
    session = active_session_label()
    sp = spread_percent(q)
    text = " ".join(c.title for c in catalysts).lower()
    if pct is not None and abs(pct) >= 20:
        flags.append("已涨/跌20%以上，优先判断是否已计价")
    if pct is not None and abs(pct) >= 6 and vol < 10000:
        flags.append(f"涨跌幅大但{session}量太小")
    if sp is not None and sp > 3:
        flags.append("买卖价差偏大")
    if q.price is not None and q.price < 2:
        flags.append("股价过低，pump风险高")
    if not catalysts and pct is not None and abs(pct) >= 6:
        flags.append("无明确新闻催化")
    for word in HIGH_RISK_WORDS:
        if word in text:
            flags.append(f"高风险关键词：{word}")
            break
    if any(c.trust_level == "low_social_or_unconfirmed" for c in catalysts):
        flags.append("社媒或未确认信息，不能作为买入依据")
    return flags


def is_form4_background(c: Catalyst) -> bool:
    return c.source == "SEC EDGAR" and str(c.raw.get("form", "")).upper() == "4"


def is_weak_yahoo_mention(c: Catalyst) -> bool:
    return c.source == "Yahoo Finance RSS" and c.trust_level == "medium" and not c.raw.get("match_in_title", True)


def solid_catalysts(catalysts: list[Catalyst]) -> list[Catalyst]:
    return [c for c in catalysts if not is_form4_background(c) and not is_weak_yahoo_mention(c)]


def score_candidate(q: Quote, catalysts: list[Catalyst], group: str, priority: str) -> tuple[int, dict, list[str]]:
    pct = active_change_percent(q)
    vol = active_volume(q) or 0
    sp = spread_percent(q)
    price_action = 0
    if pct is not None:
        abs_pct = abs(pct)
        if abs_pct >= 10:
            price_action += 12
        elif abs_pct >= 6:
            price_action += 10
        elif abs_pct >= 3:
            price_action += 7
        elif abs_pct >= 1.5:
            price_action += 4
    if vol >= 500000:
        price_action += 10
    elif vol >= 100000:
        price_action += 8
    elif vol >= 50000:
        price_action += 6
    elif vol >= 10000:
        price_action += 3
    if sp is not None:
        if sp <= 0.8:
            price_action += 4
        elif sp <= 2:
            price_action += 2
    current_price = active_price(q)
    if current_price and q.day_high and current_price > q.day_high:
        price_action += 4
    price_action = min(price_action, 30)

    catalyst_score = 0
    if catalysts:
        solid = solid_catalysts(catalysts)
        if solid:
            if any(c.trust_level == "high" for c in solid):
                catalyst_score += 12
            else:
                catalyst_score += 8
            if any(c.catalyst_type in {"财报/指引", "SEC", "合同/合作"} for c in solid):
                catalyst_score += 8
            if any(c.catalyst_type in {"分析师", "世界级企业/人物事件"} for c in solid):
                catalyst_score += 7
            if any(c.is_new for c in solid):
                catalyst_score += 5
            if any(is_weak_yahoo_mention(c) for c in catalysts):
                catalyst_score += 2
            if any(is_form4_background(c) for c in catalysts):
                catalyst_score += 2
        else:
            catalyst_score += 4 if any(c.is_new for c in catalysts) else 2
    catalyst_score = min(catalyst_score, 30)

    relevance = 0
    if group == "current_actual_holdings":
        relevance += 16
    elif group == "sold_but_still_watching":
        relevance += 10
    elif group == "watch_pool_pending_confirmation":
        relevance += 9
    text = " ".join([q.name] + [c.title for c in catalysts]).lower()
    if any(word in text for word in THEME_WORDS):
        relevance += 5
    if priority == "low":
        relevance = max(0, relevance - 4)
    relevance = min(relevance, 20)

    tradability = 0
    if vol >= 50000:
        tradability += 4
    elif vol >= 10000:
        tradability += 2
    if sp is None or sp <= 2:
        tradability += 3
    if q.price is None or q.price >= 5:
        tradability += 2
    if q.price is not None and q.price < 2:
        tradability -= 2
    tradability = max(0, min(tradability, 10))

    risk_flags = risk_flags_for(q, catalysts)
    risk_deduction = 0
    for flag in risk_flags:
        if "高风险关键词" in flag:
            risk_deduction += 8
        elif "无明确新闻" in flag:
            risk_deduction += 6
        elif "20%以上" in flag:
            risk_deduction += 5
        elif "量太小" in flag or "价差" in flag:
            risk_deduction += 4
        else:
            risk_deduction += 3
    risk_deduction = min(risk_deduction, 20)

    total = max(0, min(100, price_action + catalyst_score + relevance + tradability - risk_deduction))
    parts = {
        "量价异动": price_action,
        "催化质量": catalyst_score,
        "北斗相关性": relevance,
        "可交易性": tradability,
        "风险扣分": risk_deduction,
    }
    return int(total), parts, risk_flags


def relation_label(group: str) -> str:
    return {
        "current_actual_holdings": "实际持仓",
        "sold_but_still_watching": "已卖出仍观察",
        "watch_pool_pending_confirmation": "观察池",
    }.get(group, "全市场短线候选")


def is_new_text(catalysts: list[Catalyst]) -> str:
    if not catalysts:
        return "无明确新闻"
    if any(c.is_new for c in catalysts):
        return "新消息"
    return "旧消息新发酵" if catalysts else "旧消息重复"


def priced_in_text(q: Quote, catalysts: list[Catalyst]) -> str:
    pct = active_change_percent(q)
    if pct is None:
        return "待确认"
    if abs(pct) >= 20:
        return "高度已计价"
    if abs(pct) >= 10:
        return "可能已计价"
    if catalysts and abs(pct) < 6:
        return "未完全计价"
    return "待开盘确认"


def operation_label(score: int, q: Quote, risk_flags: list[str], catalysts: list[Catalyst]) -> str:
    risk_text = " ".join(risk_flags)
    if any(word in risk_text for word in ["高风险关键词", "退市", "破产", "稀释", "诉讼"]):
        return "过滤"
    if score >= 80:
        return "强关注"
    if score >= 65:
        return "继续观察"
    if score >= 55 and catalysts:
        return "人工研究"
    return "只记录"


def alert_level(score: int) -> str:
    if score >= 80:
        return "强提醒"
    if score >= 65:
        return "观察提醒"
    if score >= 50:
        return "只看"
    return "过滤"


def candidate_from_quote(q: Quote, relation_data: dict, now_utc: datetime, include_news: bool = True) -> Candidate:
    group, configured_name, priority, _ = relation_data.get(q.symbol, ("market_scan", q.name or q.symbol, "market", []))
    name = configured_name if configured_name and configured_name != q.symbol else (q.name or q.symbol)
    catalysts = catalysts_for_ticker(q.symbol, now_utc, max_items=5, company_name=q.name) if include_news else []
    score, parts, risks = score_candidate(q, catalysts, group, priority)
    label = operation_label(score, q, risks, catalysts)
    cand = Candidate(
        symbol=q.symbol,
        company_name=name,
        quote=q,
        catalysts=catalysts,
        relation=relation_label(group),
        group=group,
        score=score,
        score_parts=parts,
        risk_flags=risks,
        operation_label=label,
        alert_level=alert_level(score),
    )
    if score < 50:
        cand.is_noise = True
        if risks:
            cand.noise_reason = risks[0]
        elif not catalysts and active_change_percent(q, now_utc) is None:
            cand.noise_reason = "无当前时段异动或无可确认数据"
        elif not catalysts:
            cand.noise_reason = "无明确新闻"
        else:
            cand.noise_reason = "分数低于50"
    return cand


def format_volume(value: int | None) -> str:
    if value is None:
        return "未知"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(value)


def format_pct(value: float | None) -> str:
    if value is None:
        return "未知"
    word = "涨" if value >= 0 else "跌"
    return f"{word}{abs(value):.2f}%"


def format_price(value: float | None) -> str:
    if value is None:
        return "价格未知"
    return f"${value:,.2f}"


def quote_brief(q: Quote) -> str:
    return f"{active_session_label()} {format_price(active_price(q))}｜{format_pct(active_change_percent(q))}"


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def normalized_title_key(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def load_translation_cache() -> dict[str, str]:
    global TRANSLATION_CACHE
    if TRANSLATION_CACHE is not None:
        return TRANSLATION_CACHE
    if TRANSLATION_CACHE_PATH.exists():
        try:
            TRANSLATION_CACHE = json.loads(TRANSLATION_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            TRANSLATION_CACHE = {}
    else:
        TRANSLATION_CACHE = {}
    return TRANSLATION_CACHE


def save_translation_cache() -> None:
    if TRANSLATION_CACHE is None:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        TRANSLATION_CACHE_PATH.write_text(json.dumps(TRANSLATION_CACHE, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log(f"translation cache save skipped: {exc}")


def local_event_summary(title: str) -> str:
    text = title.lower()
    if "price target" in text or "upgrade" in text or "downgrade" in text or "analyst" in text:
        return f"分析师或目标价相关消息：{title}"
    if "earnings" in text or "revenue" in text or "guidance" in text or "results" in text:
        return f"财报、收入或指引相关消息：{title}"
    if "contract" in text or "partnership" in text or "deal" in text or "order" in text:
        return f"合同、合作或订单相关消息：{title}"
    if "lawsuit" in text or "investigation" in text:
        return f"诉讼或调查风险消息：{title}"
    if "nvidia" in text or "jensen" in text or "ai" in text:
        return f"AI 产业链相关消息：{title}"
    return f"市场新闻：{title}"


def translate_title_to_zh(title: str, allow_online: bool = True) -> str:
    if not title:
        return ""
    if contains_cjk(title):
        return title
    key = normalized_title_key(title)
    if key in EXACT_EVENT_TRANSLATIONS:
        return EXACT_EVENT_TRANSLATIONS[key]
    cache = load_translation_cache()
    if title in cache:
        return cache[title]
    if not allow_online:
        translated = local_event_summary(title)
        cache[title] = translated
        save_translation_cache()
        return translated
    try:
        url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
            {
                "client": "gtx",
                "sl": "en",
                "tl": "zh-CN",
                "dt": "t",
                "q": title,
            }
        )
        data = json.loads(http_get(url, timeout=8, headers={"Referer": "https://translate.google.com/"}))
        translated = "".join(part[0] for part in data[0] if part and part[0]).strip()
        if translated and translated.lower() != title.lower():
            cache[title] = translated
            save_translation_cache()
            return translated
    except Exception as exc:
        log(f"translation skipped for title={title[:60]!r}: {exc}")
    translated = local_event_summary(title)
    cache[title] = translated
    save_translation_cache()
    return translated


def catalyst_title_zh(c: Catalyst | None, allow_online: bool = True) -> str:
    if not c:
        return "暂无明确催化"
    return translate_title_to_zh(c.title, allow_online=allow_online)


def catalyst_time(c: Catalyst | None, zone: ZoneInfo) -> str:
    if not c or not c.published_at:
        return "未知"
    bj = c.published_at.astimezone(ZoneInfo("Asia/Shanghai"))
    et = c.published_at.astimezone(zone)
    return f"北京时间 {bj:%Y-%m-%d %H:%M} / 美东 {et:%Y-%m-%d %H:%M}"


def relative_time_zh(dt: datetime | None, now_utc: datetime | None = None) -> str:
    if not dt:
        return "距今未知"
    now_utc = now_utc or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = int((now_utc - dt.astimezone(timezone.utc)).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"约{minutes}分钟前"
    hours = minutes // 60
    if hours < 48:
        return f"约{hours}小时前"
    days = hours // 24
    return f"约{days}天前"


def catalyst_time_annotation(c: Catalyst | None, now_utc: datetime | None = None) -> str:
    if not c or not c.published_at:
        return "消息时间待确认"
    now_utc = now_utc or datetime.now(timezone.utc)
    bj = c.published_at.astimezone(ZoneInfo("Asia/Shanghai"))
    et = c.published_at.astimezone(ZoneInfo("America/New_York"))
    freshness = "新消息" if c.is_new else "旧消息新发酵"
    return f"消息时间：北京时间 {bj:%Y-%m-%d %H:%M} / 美东 {et:%Y-%m-%d %H:%M} / {relative_time_zh(c.published_at, now_utc)} / {freshness}"


def event_chain(c: Candidate) -> str:
    if not c.catalysts:
        return "暂未抓到明确新闻/SEC催化，等待自动源继续更新。"
    top = c.catalysts[0]
    source = top.source or "来源待确认"
    return f"{catalyst_title_zh(top)}；来源：{source}。"


def event_annotation(c: Candidate) -> str:
    top = c.catalysts[0] if c.catalysts else None
    text = " ".join(
        [
            c.symbol,
            c.company_name,
            c.relation,
            top.title if top else "",
            catalyst_title_zh(top, allow_online=False) if top else "",
            top.catalyst_type if top else "",
            " ".join(c.risk_flags),
        ]
    ).lower()
    tags: list[str] = []

    if any(word in text for word in ["lawsuit", "investigation", "bankruptcy", "delisting", "dilution", "高风险关键词"]):
        tags.append("高风险留痕")
    if any(word in text for word in ["nvidia", "jensen", "marvell", "broadcom", "custom ai chip", "semiconductor", "ai 芯片"]):
        tags.append("AI芯片链")
    if any(word in text for word in ["micron", "hbm", "dram", "memory", "western digital", "storage", "存储"]):
        tags.append("存储/HBM链")
    if any(word in text for word in ["oracle", "data center", "数据中心", "clean power", "arm shift"]):
        tags.append("AI数据中心")
    if any(word in text for word in ["nuclear", "nuscale", "smr", "核电"]):
        tags.append("核电/SMR")
    if any(word in text for word in ["rigetti", "quantum", "量子"]):
        tags.append("量子计算")
    if any(word in text for word in ["circle", "stablecoin", "usdc", "crypto", "加密", "稳定币"]):
        tags.append("稳定币/加密")
    if any(word in text for word in ["gold", "gld", "iau", "treasury", "dollar", "黄金"]):
        tags.append("黄金/宏观")
    if any(word in text for word in ["coca-cola", "pepsico", "american electric", "american water", "公用事业"]):
        tags.append("防守持仓")

    if top:
        ctype = top.catalyst_type
        if ctype == "世界级企业/人物事件":
            tags.append("世界级人物/企业催化")
        elif ctype == "高风险事件":
            tags.append("高风险事件")
        elif ctype == "财报/指引":
            tags.append("财报/指引")
        elif ctype == "SEC":
            tags.append("SEC披露")
        elif ctype == "合同/合作":
            tags.append("合同/合作")
        elif ctype == "分析师":
            tags.append("分析师动作")
        else:
            tags.append("新闻催化")
    else:
        tags.append("无明确新闻")

    pct = active_change_percent(c.quote)
    vol = active_volume(c.quote) or 0
    session = active_session_label()
    if pct is not None and abs(pct) >= 6 and vol >= 50_000:
        tags.append(f"{session}量价确认")
    elif vol >= 50_000:
        tags.append(f"{session}放量")
    else:
        tags.append(f"{session}量待确认")

    if c.group == "current_actual_holdings":
        tags.append("实际持仓相关")
    elif c.group == "sold_but_still_watching":
        tags.append("已卖出观察")
    elif c.group == "watch_pool_pending_confirmation":
        tags.append("观察池线索")
    else:
        tags.append("全市场候选")

    deduped = list(dict.fromkeys(tags))
    return " / ".join(deduped[:5])


def risk_text(c: Candidate) -> str:
    if c.risk_flags:
        return c.risk_flags[0]
    session = active_session_label()
    vol = active_volume(c.quote)
    if vol is not None and vol < 50000:
        return f"{session}量不足，需确认是否继续放量。"
    return f"{session}波动和价差风险，需人工确认。"


def reason_text(c: Candidate) -> str:
    parts = c.score_parts
    return f"分数 {c.score}/100；量价 {parts['量价异动']}，催化 {parts['催化质量']}，北斗相关 {parts['北斗相关性']}，风险扣 {parts['风险扣分']}。"


def generate_report(candidates: list[Candidate], noises: list[Candidate], now_utc: datetime) -> str:
    bj = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    et_zone = ZoneInfo("America/New_York")
    et = now_utc.astimezone(et_zone)
    session = market_session(now_utc)
    session_label = str(session["label"])
    top = [c for c in candidates if not c.is_noise][:7]
    names = "、".join(c.symbol for c in top[:3]) if top else "暂无高置信候选"

    lines: list[str] = []
    lines.append("====================【北斗全时段异动雷达】====================")
    lines.append("")
    lines.append("🕒【扫描时间】")
    lines.append(f"北京时间：{bj:%Y-%m-%d %H:%M}")
    lines.append(f"美东时间：{et:%Y-%m-%d %H:%M}")
    lines.append(f"当前美股时段：{session_label}（{session['note']}）")
    if not session.get("has_live_price_source", False):
        lines.append(f"价格说明：{session['price_note']}")
    lines.append("")
    lines.append("【一句话结论】")
    lines.append("扫描范围：Nasdaq 100 + 我的持仓/观察池 + 全市场异动候选；持仓池只是优先标记，不是扫描边界。")
    has_current_move = any(active_change_percent(c.quote, now_utc) is not None for c in top)
    if top:
        if has_current_move:
            lines.append(f"当前{session_label}最值得盯的是：{names}。不要自动追，先看后续30-60分钟是否继续放量。")
        else:
            lines.append(f"当前处于{session_label}，先只记录新闻/SEC线索：{names}。不要自动追，等下一轮量价确认。")
    else:
        lines.append("当前暂未筛出同时满足真实催化、当前量价和可交易性的高置信候选；不要为了异动本身追。")
    lines.append("")

    for idx, c in enumerate(top, 1):
        catalyst = c.catalysts[0] if c.catalysts else None
        ctype = catalyst.catalyst_type if catalyst else "待确认"
        lines.append(f"【{idx}】{c.symbol} / {c.company_name}｜{quote_brief(c.quote)}")
        lines.append(f"当前异动：{format_pct(active_change_percent(c.quote, now_utc))}，成交量 {format_volume(active_volume(c.quote, now_utc))}")
        lines.append(f"消息发布时间：{catalyst_time(catalyst, et_zone)}")
        lines.append(f"事件链：{event_chain(c)}")
        lines.append(f"事件标注：{event_annotation(c)}")
        lines.append(f"时间标注：{catalyst_time_annotation(catalyst, now_utc)}")
        lines.append(f"催化类型：{ctype}")
        lines.append(f"北斗相关性：{c.relation}")
        lines.append(f"是否重复：{is_new_text(c.catalysts)}")
        lines.append(f"是否已计价：{priced_in_text(c.quote, c.catalysts)}")
        lines.append(f"风险：{risk_text(c)}")
        if c.cross_checks:
            lines.extend(format_cross_checks(c.cross_checks))
        lines.append(f"信息处理标签：{c.operation_label}")
        lines.append(f"理由：{reason_text(c)}")
        lines.append("")

    lines.append("【本次过滤掉的典型噪音】")
    filtered = noises[:3]
    if filtered:
        for n in filtered:
            lines.append(f"- {n.symbol}：{n.noise_reason or '分数低于50'}。")
    else:
        lines.append("- 暂无典型噪音；可能是当前非交易时段或公开源未返回当前时段数据。")
    lines.append("")
    lines.append("安全边界：这不是自动交易系统，不自动下单，不承诺盈利；所有提醒只是人工判断前的线索。")
    return "\n".join(lines)


def catalyst_to_payload(c: Catalyst) -> dict:
    return {
        "ticker": c.ticker,
        "title": c.title,
        "title_zh": catalyst_title_zh(c, allow_online=False),
        "source": c.source,
        "url": c.url,
        "published_at": c.published_at.isoformat() if c.published_at else None,
        "catalyst_type": c.catalyst_type,
        "trust_level": c.trust_level,
        "is_new": c.is_new,
        "raw": c.raw,
    }


def candidate_to_payload(c: Candidate) -> dict:
    return {
        "symbol": c.symbol,
        "company_name": c.company_name,
        "relation": c.relation,
        "group": c.group,
        "score": c.score,
        "score_parts": c.score_parts,
        "risk_flags": c.risk_flags,
        "information_label": c.operation_label,
        "alert_level": c.alert_level,
        "quote": {
            "symbol": c.quote.symbol,
            "name": c.quote.name,
            "price": c.quote.price,
            "regular_change_percent": c.quote.regular_change_percent,
            "overnight_price": c.quote.overnight_price,
            "overnight_change_percent": c.quote.overnight_change_percent,
            "overnight_volume": c.quote.overnight_volume,
            "premarket_price": c.quote.premarket_price,
            "premarket_change_percent": c.quote.premarket_change_percent,
            "premarket_volume": c.quote.premarket_volume,
            "postmarket_price": c.quote.postmarket_price,
            "postmarket_change_percent": c.quote.postmarket_change_percent,
            "postmarket_volume": c.quote.postmarket_volume,
            "regular_volume": c.quote.regular_volume,
            "active_session": active_session_label(),
            "active_price": active_price(c.quote),
            "active_change_percent": active_change_percent(c.quote),
            "active_volume": active_volume(c.quote),
            "source": c.quote.source,
        },
        "catalysts": [catalyst_to_payload(item) for item in c.catalysts],
        "cross_checks": {key: asdict(value) for key, value in c.cross_checks.items()},
        "is_noise": c.is_noise,
        "noise_reason": c.noise_reason,
    }


def source_check_to_zh_payload(check: SourceCheck) -> dict:
    return {
        "数据源": check.source,
        "状态": check.status,
        "摘要": check.summary,
        "网址": check.url,
        "自动化级别": check.automation_level,
        "需要登录": check.requires_login,
        "需要APIKey": check.needs_api_key,
    }


def candidate_to_zh_payload(c: Candidate) -> dict:
    current_quote = {
        "数据源": c.quote.source,
        "时段": active_session_label(),
        "当前价格说明": market_session().get("price_note"),
        "当前价格": active_price(c.quote),
        "当前涨跌幅": active_change_percent(c.quote),
        "当前成交量": active_volume(c.quote),
        "常规价格": c.quote.price,
        "常规涨跌幅": c.quote.regular_change_percent,
        "常规成交量": c.quote.regular_volume,
        "夜盘价格": c.quote.overnight_price,
        "夜盘涨跌幅": c.quote.overnight_change_percent,
        "夜盘成交量": c.quote.overnight_volume,
        "盘前价格": c.quote.premarket_price,
        "盘前涨跌幅": c.quote.premarket_change_percent,
        "盘前成交量": c.quote.premarket_volume,
        "盘后价格": c.quote.postmarket_price,
        "盘后涨跌幅": c.quote.postmarket_change_percent,
        "盘后成交量": c.quote.postmarket_volume,
    }
    return {
        "股票代码": c.symbol,
        "公司名称": c.company_name,
        "所属类型": c.relation,
        "短线发酵分数": c.score,
        "分数明细": c.score_parts,
        "风险标签": c.risk_flags,
        "事件标注": event_annotation(c),
        "时间标注": catalyst_time_annotation(c.catalysts[0] if c.catalysts else None),
        "信息处理标签": c.operation_label,
        "提醒级别": c.alert_level,
        "当前行情": current_quote,
        "盘前行情": current_quote,
        "催化来源": [
            {
                "标题": item.title,
                "中文标题": catalyst_title_zh(item, allow_online=idx == 0),
                "原文标题": item.title,
                "来源": item.source,
                "网址": item.url,
                "发布时间": item.published_at.isoformat() if item.published_at else None,
                "时间标注": catalyst_time_annotation(item),
                "催化类型": item.catalyst_type,
                "可信度": item.trust_level,
                "是否新消息": item.is_new,
            }
            for idx, item in enumerate(c.catalysts)
        ],
        "五站交叉验证": {
            key: source_check_to_zh_payload(value)
            for key, value in c.cross_checks.items()
        },
        "是否噪音": c.is_noise,
        "过滤原因": c.noise_reason,
    }


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


def important_reason(c: Candidate) -> str:
    pct = active_change_percent(c.quote)
    vol = active_volume(c.quote) or 0
    solid = solid_catalysts(c.catalysts)
    reasons: list[str] = []
    if c.score >= 80:
        reasons.append("80分以上强提醒")
    elif c.score >= 65:
        reasons.append("65分以上观察提醒")
    if c.group == "current_actual_holdings" and c.score >= 60:
        reasons.append("实际持仓相关")
    if pct is not None and abs(pct) >= 6 and vol >= 50000:
        reasons.append("当前时段量价异动明显")
    if c.score >= 60 and any(catalyst.trust_level == "high" and catalyst.is_new for catalyst in solid):
        reasons.append("高可信新消息")
    risk_text = " ".join(c.risk_flags)
    if any(word in risk_text for word in ["高风险关键词", "20%以上", "退市", "破产", "稀释", "诉讼"]):
        reasons.append("高风险需单独留痕")
    return "；".join(dict.fromkeys(reasons))


def is_important_candidate(c: Candidate) -> bool:
    return bool(important_reason(c))


def stored_record_should_remain(record: dict) -> bool:
    score = record.get("短线发酵分数") or 0
    relation = record.get("所属类型") or ""
    reason = record.get("置顶原因") or ""
    risk_text = " ".join(record.get("风险标签") or [])
    if score >= 65:
        return True
    if relation == "实际持仓" and score >= 60:
        return True
    if "当前时段量价异动明显" in reason or "盘前量价异动明显" in reason:
        return True
    if "高风险需单独留痕" in reason:
        return True
    if any(word in risk_text for word in ["高风险关键词", "20%以上", "退市", "破产", "稀释", "诉讼"]):
        return True
    return False


def important_record_id(c: Candidate, now_utc: datetime) -> str:
    top = c.catalysts[0] if c.catalysts else None
    event_key = top.url or top.title if top else f"{now_utc:%Y-%m-%d}"
    raw = f"{c.symbol}|{event_key}|{c.group}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def important_record_from_candidate(
    c: Candidate,
    now_utc: datetime,
    existing: dict | None = None,
) -> dict:
    existing = existing or {}
    expires_at = now_utc + timedelta(minutes=IMPORTANT_PIN_MINUTES)
    old_expires = parse_iso_datetime(existing.get("置顶到UTC"))
    if old_expires and old_expires > expires_at:
        expires_at = old_expires
    first_seen = existing.get("首次记录UTC") or now_utc.isoformat()
    record = candidate_to_zh_payload(c)
    record.update(
        {
            "重要ID": important_record_id(c, now_utc),
            "重要等级": "强" if c.score >= 80 or c.alert_level == "强提醒" else "观察",
            "置顶原因": important_reason(c),
            "首次记录UTC": first_seen,
            "最近出现UTC": now_utc.isoformat(),
            "置顶到UTC": expires_at.isoformat(),
            "置顶保留分钟": IMPORTANT_PIN_MINUTES,
        }
    )
    return record


def append_important_log(record: dict, now_utc: datetime) -> None:
    IMPORTANT_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "记录时间UTC": now_utc.isoformat(),
        "重要ID": record.get("重要ID"),
        "股票代码": record.get("股票代码"),
        "公司名称": record.get("公司名称"),
        "短线发酵分数": record.get("短线发酵分数"),
        "信息处理标签": record.get("信息处理标签"),
        "置顶原因": record.get("置顶原因"),
        "催化来源": (record.get("催化来源") or [])[:2],
        "当前行情": record.get("当前行情") or record.get("盘前行情"),
        "盘前行情": record.get("盘前行情"),
    }
    with (IMPORTANT_DIR / "important_records.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_daily_important_markdown(record: dict, now_utc: datetime) -> None:
    IMPORTANT_DIR.mkdir(parents=True, exist_ok=True)
    bj = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    cats = record.get("催化来源") or []
    quote = record.get("当前行情") or record.get("盘前行情") or {}
    title = (cats[0].get("中文标题") or cats[0].get("标题")) if cats else "暂无明确催化"
    source = cats[0].get("来源") if cats else "来源待确认"
    line = (
        f"\n## {bj:%Y-%m-%d %H:%M} | {record.get('股票代码')} / {record.get('公司名称')}\n"
        f"- 分数：{record.get('短线发酵分数')}/100；标签：{record.get('信息处理标签')}；置顶原因：{record.get('置顶原因')}\n"
        f"- {quote.get('时段') or '当前'}：{quote.get('当前涨跌幅')}%；量：{quote.get('当前成交量')}；所属：{record.get('所属类型')}\n"
        f"- 事件：{title}；来源：{source}\n"
        f"- 风险：{(record.get('风险标签') or ['当前时段波动和价差风险，需人工确认'])[0]}\n"
        f"- 重要ID：{record.get('重要ID')}；置顶到UTC：{record.get('置顶到UTC')}\n"
    )
    path = IMPORTANT_DIR / f"{bj:%Y-%m-%d}_important.md"
    if not path.exists():
        path.write_text(
            "# 北斗全时段重要消息记录\n\n"
            "这里记录被置顶的重要消息。它不是交易指令，只是错过实时刷新时的回看线索。\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def write_important_records(candidates: list[Candidate], now_utc: datetime) -> dict:
    IMPORTANT_DIR.mkdir(parents=True, exist_ok=True)
    state_path = IMPORTANT_DIR / "important_records.json"
    old_active: list[dict] = []
    if state_path.exists():
        try:
            old_active = json.loads(state_path.read_text(encoding="utf-8")).get("重要消息", [])
        except Exception:
            old_active = []

    active_by_id: dict[str, dict] = {}
    for record in old_active:
        expires_at = parse_iso_datetime(record.get("置顶到UTC"))
        if expires_at and expires_at > now_utc and stored_record_should_remain(record):
            active_by_id[record.get("重要ID", "")] = record

    new_ids: list[str] = []
    for cand in candidates:
        if cand.is_noise or not is_important_candidate(cand):
            continue
        record_id = important_record_id(cand, now_utc)
        record = important_record_from_candidate(cand, now_utc, active_by_id.get(record_id))
        if record_id not in active_by_id:
            append_important_log(record, now_utc)
            append_daily_important_markdown(record, now_utc)
            new_ids.append(record_id)
        active_by_id[record_id] = record

    active = list(active_by_id.values())
    active.sort(
        key=lambda item: (
            item.get("重要等级") == "强",
            item.get("短线发酵分数") or 0,
            parse_iso_datetime(item.get("最近出现UTC")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    active = active[:IMPORTANT_ACTIVE_LIMIT]
    for item in active:
        expires_at = parse_iso_datetime(item.get("置顶到UTC"))
        item["置顶剩余秒"] = max(0, int((expires_at - now_utc).total_seconds())) if expires_at else 0

    bj = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    payload = {
        "模块": "北斗重要消息钉板",
        "更新时间UTC": now_utc.isoformat(),
        "北京时间": bj.strftime("%Y-%m-%d %H:%M:%S"),
        "置顶保留分钟": IMPORTANT_PIN_MINUTES,
        "说明": "重要消息至少保留约15分钟；普通候选仍按最新扫描实时更新。",
        "重要消息": active,
        "本次新增重要ID": new_ids,
        "历史JSONL": str(IMPORTANT_DIR / "important_records.jsonl"),
        "当天Markdown": str(IMPORTANT_DIR / f"{bj:%Y-%m-%d}_important.md"),
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def write_latest_json(
    report_path: Path,
    report_text: str,
    candidates: list[Candidate],
    noises: list[Candidate],
    now_utc: datetime,
) -> Path:
    bj = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    session = market_session(now_utc)
    payload = {
        "module": "beidou_full_session_mover_radar",
        "generated_at_utc": now_utc.isoformat(),
        "beijing_time": bj.strftime("%Y-%m-%d %H:%M:%S"),
        "eastern_time": et.strftime("%Y-%m-%d %H:%M:%S"),
        "market_session": session,
        "report_path": str(report_path),
        "report_text": report_text,
        "scan_universe": "Nasdaq 100 + 我的持仓/观察池 + 全市场异动候选",
        "top_candidates": [candidate_to_payload(c) for c in candidates[:7]],
        "filtered_noise": [candidate_to_payload(c) for c in noises[:10]],
        "safety_boundary": "这不是自动交易系统，不自动下单，不承诺盈利；所有提醒只是人工判断前的信息线索。",
    }
    json_path = REPORT_DIR / "latest.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    dated_json = report_path.with_suffix(".json")
    dated_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    important_payload = write_important_records(candidates, now_utc)
    zh_payload = {
        "模块": "北斗美股全时段异动雷达",
        "生成时间UTC": now_utc.isoformat(),
        "北京时间": bj.strftime("%Y-%m-%d %H:%M:%S"),
        "美东时间": et.strftime("%Y-%m-%d %H:%M:%S"),
        "当前美股时段": session,
        "报告文件": str(report_path),
        "中文报告": report_text,
        "扫描范围": "Nasdaq 100 + 我的持仓/观察池 + 全市场异动候选；持仓池只是优先标记，不是扫描边界。",
        "重要置顶": important_payload.get("重要消息", []),
        "重要消息记录": {
            "说明": important_payload.get("说明"),
            "置顶保留分钟": important_payload.get("置顶保留分钟"),
            "历史JSONL": important_payload.get("历史JSONL"),
            "当天Markdown": important_payload.get("当天Markdown"),
        },
        "候选股票": [candidate_to_zh_payload(c) for c in candidates[:7]],
        "过滤噪音": [candidate_to_zh_payload(c) for c in noises[:10]],
        "安全边界": "这不是自动交易系统，不自动下单，不承诺盈利；所有提醒只是人工判断前的信息线索。",
    }
    zh_json_path = REPORT_DIR / "latest_zh.json"
    zh_json_path.write_text(json.dumps(zh_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.with_name(report_path.stem + "_zh.json").write_text(
        json.dumps(zh_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path


def write_html_view(report_path: Path, report_text: str, now_utc: datetime) -> Path:
    bj = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    escaped = html_lib.escape(report_text)
    body = escaped.replace("\n", "<br>")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>北斗美股全时段异动雷达</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #071014;
      --panel: #0f1c22;
      --text: #eaf5f4;
      --muted: #9db1af;
      --line: #24414a;
      --accent: #2bd4a7;
      --warn: #ffc857;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
      line-height: 1.62;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      border-bottom: 1px solid var(--line);
      background: rgba(7, 16, 20, .94);
      backdrop-filter: blur(10px);
    }}
    .wrap {{
      width: min(980px, calc(100% - 28px));
      margin: 0 auto;
      padding: 18px 0;
    }}
    h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      margin-top: 4px;
      font-size: 13px;
    }}
    main .wrap {{
      padding: 20px 0 36px;
    }}
    .report {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 18px;
      font-size: 15px;
      overflow-wrap: anywhere;
      box-shadow: 0 16px 40px rgba(0,0,0,.28);
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-top: 10px;
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 13px;
    }}
    .pill strong {{ color: var(--accent); font-weight: 650; }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>北斗美股全时段异动雷达</h1>
      <div class="meta">本地报告：{html_lib.escape(str(report_path))}</div>
      <div class="pill"><strong>安全边界</strong> 只做信息雷达，不自动下单，不给确定性买卖建议</div>
    </div>
  </header>
  <main>
    <div class="wrap">
      <section class="report">{body}</section>
      <p class="meta">生成时间：北京时间 {bj:%Y-%m-%d %H:%M:%S}</p>
    </div>
  </main>
</body>
</html>
"""
    html_path = REPORT_DIR / "latest.html"
    html_path.write_text(html, encoding="utf-8")
    dated_html = report_path.with_suffix(".html")
    dated_html.write_text(html, encoding="utf-8")
    return html_path


def run_scan(include_news: bool = True) -> tuple[Path, list[Candidate], list[Candidate]]:
    now_utc = datetime.now(timezone.utc)
    relation_data, base_symbols, _ = relation_maps()
    seed_symbols = list(base_symbols)
    nasdaq100_symbols = get_nasdaq100_symbols()
    seed_symbols.extend(nasdaq100_symbols)
    seed_symbols.extend(discover_polygon_movers())
    seed_symbols.extend(discover_yahoo_screeners())
    seed_symbols = list(dict.fromkeys([s.upper() for s in seed_symbols if s]))

    quotes = fetch_tradingview_quotes(seed_symbols)
    yahoo_quotes = fetch_yahoo_quotes(
        [s for s in seed_symbols if s not in quotes],
        fallback_symbols={s.upper() for s in base_symbols},
    )
    quotes.update(yahoo_quotes)
    for symbol in seed_symbols:
        if symbol not in quotes:
            fh = fetch_finnhub_quote(symbol)
            if fh:
                quotes[symbol] = fh

    candidates: list[Candidate] = []
    noises: list[Candidate] = []
    ranked_symbols = sorted(
        quotes.keys(),
        key=lambda s: (
            s in relation_data,
            abs(active_change_percent(quotes[s], now_utc) or 0),
            active_volume(quotes[s], now_utc) or 0,
        ),
        reverse=True,
    )
    news_symbols = {s for s in ranked_symbols[:20]}
    news_symbols.update(s for s in base_symbols if s != "GOLD_BASKET")

    for symbol, quote in quotes.items():
        pct = active_change_percent(quote, now_utc)
        vol = active_volume(quote, now_utc) or 0
        is_watch = symbol in relation_data
        needs_eval = is_watch or (pct is not None and abs(pct) >= 2) or vol >= 50000
        if not needs_eval:
            continue
        cand = candidate_from_quote(quote, relation_data, now_utc, include_news=include_news and symbol in news_symbols)
        if cand.is_noise:
            noises.append(cand)
        else:
            candidates.append(cand)

    candidates.sort(key=lambda c: (c.score, abs(active_change_percent(c.quote, now_utc) or 0), active_volume(c.quote, now_utc) or 0), reverse=True)
    noises.sort(key=lambda c: (abs(active_change_percent(c.quote, now_utc) or 0), active_volume(c.quote, now_utc) or 0), reverse=True)

    for cand in candidates[:3]:
        cand.cross_checks = five_site_cross_check(cand.symbol)

    report = generate_report(candidates, noises, now_utc)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    bj = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    report_path = REPORT_DIR / f"{bj:%Y-%m-%d_%H%M}.md"
    report_path.write_text(report, encoding="utf-8")
    write_latest_json(report_path, report, candidates, noises, now_utc)
    write_html_view(report_path, report, now_utc)
    log(f"scan complete report={report_path} candidates={len(candidates)} noises={len(noises)}")
    return report_path, candidates, noises


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the 北斗全时段异动雷达.")
    parser.add_argument("--notify", action="store_true", help="Send configured notifications after saving the report")
    parser.add_argument("--no-news", action="store_true", help="Skip Yahoo RSS and SEC catalyst lookups")
    args = parser.parse_args(argv)

    report_path, candidates, noises = run_scan(include_news=not args.no_news)
    print(report_path)
    print(report_path.read_text(encoding="utf-8"))

    if args.notify:
        if send_alert:
            results = send_alert(report_path)
            print("通知结果：", json.dumps(results, ensure_ascii=False))
        else:
            print("通知模块不可用，已只保存报告。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
