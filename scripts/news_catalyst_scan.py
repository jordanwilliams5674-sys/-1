#!/usr/bin/env python3
"""News and SEC catalyst scanner for the Beidou premarket radar."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "watchlist.yaml"
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports" / "premarket"
USER_AGENT = "premarket_mover_radar/1.0 contact=295765031@qq.com"

SEC_FORMS = {"8-K", "S-3", "424B2", "424B3", "424B4", "424B5", "4", "10-Q", "10-K"}
HIGH_TRUST_WORDS = {
    "sec",
    "reuters",
    "bloomberg",
    "wsj",
    "wall street journal",
    "cnbc",
    "financial times",
    "associated press",
    "ap news",
    "business wire",
    "prnewswire",
}

COMMON_COMPANY_WORDS = {
    "adr",
    "ads",
    "class",
    "common",
    "company",
    "corp",
    "corporation",
    "holdings",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "ordinary",
    "plc",
    "shares",
    "stock",
}

TICKER_ALIASES = {
    "AEP": ["american electric power"],
    "AMKR": ["amkor"],
    "ASX": ["ase technology", "advanced semiconductor engineering"],
    "AWK": ["american water works"],
    "CEG": ["constellation energy"],
    "CRCL": ["circle"],
    "CRWD": ["crowdstrike"],
    "CSIQ": ["canadian solar"],
    "INTC": ["intel"],
    "KO": ["coca-cola", "coca cola"],
    "MRVL": ["marvell"],
    "MU": ["micron"],
    "NOK": ["nokia"],
    "NRG": ["nrg energy"],
    "NVDA": ["nvidia"],
    "ORCL": ["oracle"],
    "OUST": ["ouster"],
    "PEP": ["pepsico", "pepsi"],
    "QCOM": ["qualcomm"],
    "RGTI": ["rigetti"],
    "SMR": ["nuscale"],
    "TSLA": ["tesla", "spacex"],
    "VST": ["vistra"],
    "WDC": ["western digital"],
}

YAHOO_EXCLUDE_TERMS = {
    "IAU": ["i-80 gold", "nyse american: iaux", "tsx: iau"],
}


@dataclass
class WatchItem:
    ticker: str
    name: str = ""
    group: str = "unknown"
    priority: str = "medium"
    notes: str = ""
    mapping_symbols: list[str] = field(default_factory=list)
    quote_enabled: bool = True


@dataclass
class Catalyst:
    ticker: str
    title: str
    source: str
    url: str = ""
    published_at: datetime | None = None
    catalyst_type: str = "新闻"
    trust_level: str = "medium"
    is_new: bool = False
    raw: dict = field(default_factory=dict)


def http_get(url: str, timeout: int = 20, headers: dict | None = None) -> str:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_json(url: str, timeout: int = 20, headers: dict | None = None) -> dict:
    return json.loads(http_get(url, timeout=timeout, headers=headers))


def parse_watchlist_config(path: Path = CONFIG_PATH) -> tuple[list[WatchItem], dict]:
    text = path.read_text(encoding="utf-8")
    groups = {"current_actual_holdings", "sold_but_still_watching", "watch_pool_pending_confirmation"}
    items: list[WatchItem] = []
    current_group = "unknown"
    current: WatchItem | None = None
    meta = {"scan_times": [], "email_to": "295765031@qq.com"}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if re.match(r'^\s*-\s*"\d{2}:\d{2}"', line):
            meta["scan_times"].append(stripped.strip("- ").strip('"'))
        if stripped.startswith("email_to:"):
            meta["email_to"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")

        group_match = re.match(r"^\s{2}([a-z_]+):\s*$", line)
        if group_match and group_match.group(1) in groups:
            current_group = group_match.group(1)
            current = None
            continue

        ticker_match = re.match(r"^\s*-\s*ticker:\s*(.+?)\s*$", line)
        if ticker_match:
            current = WatchItem(ticker=ticker_match.group(1).strip(), group=current_group)
            items.append(current)
            continue

        if current and ":" in stripped:
            key, value = stripped.split(":", 1)
            value = value.strip().strip('"').strip("'")
            if key == "name":
                current.name = value
            elif key == "priority":
                current.priority = value
            elif key == "notes":
                current.notes = value
            elif key == "mapping_symbols":
                current.mapping_symbols = [part.strip() for part in value.split(",") if part.strip()]
            elif key == "quote_enabled":
                current.quote_enabled = value.lower() not in {"false", "no", "0"}

    return items, meta


def latest_sec_company_tickers() -> dict:
    cache_path = LOG_DIR / "sec_company_tickers.json"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < 7 * 86400:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = http_json("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": USER_AGENT})
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def cik_for_ticker(ticker: str) -> str | None:
    if not re.match(r"^[A-Z][A-Z0-9.]{0,9}$", ticker):
        return None
    try:
        data = latest_sec_company_tickers()
    except Exception:
        return None
    for row in data.values():
        if str(row.get("ticker", "")).upper() == ticker.upper():
            return str(row.get("cik_str", "")).zfill(10)
    return None


def parse_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def classify_catalyst(title: str, source: str = "", summary: str = "") -> tuple[str, str]:
    text = f"{title} {summary} {source}".lower()
    catalyst_type = "新闻"
    if any(word in text for word in ["earnings", "results", "revenue", "guidance", "quarter", "profit"]):
        catalyst_type = "财报/指引"
    if any(word in text for word in ["8-k", "10-q", "10-k", "s-3", "424b", "form 4", "sec filing"]):
        catalyst_type = "SEC"
    if any(word in text for word in ["contract", "award", "order", "partnership", "customer", "deal"]):
        catalyst_type = "合同/合作"
    if any(word in text for word in ["upgrade", "downgrade", "price target", "initiates", "analyst"]):
        catalyst_type = "分析师"
    if any(word in text for word in ["nvidia", "jensen", "openai", "microsoft", "apple", "meta", "google", "amazon"]):
        catalyst_type = "世界级企业/人物事件"
    if any(
        word in text
        for word in [
            "public offering",
            "registered direct",
            "securities offering",
            "share offering",
            "stock offering",
            "atm offering",
            "dilution",
            "bankruptcy",
            "delisting",
            "lawsuit",
        ]
    ):
        catalyst_type = "高风险事件"

    trust = "high" if any(word in text for word in HIGH_TRUST_WORDS) else "medium"
    if any(word in text for word in ["twitter", "x.com", "reddit", "rumor", "unconfirmed"]):
        trust = "low_social_or_unconfirmed"
    return catalyst_type, trust


def normalized_company_terms(ticker: str, company_name: str = "") -> list[str]:
    terms = list(TICKER_ALIASES.get(ticker.upper(), []))
    cleaned = re.sub(r"[^A-Za-z0-9 &.-]+", " ", company_name).strip().lower()
    if cleaned:
        for suffix in [
            " common stock",
            " ordinary shares",
            " inc.",
            " inc",
            " corporation",
            " corp.",
            " corp",
            " company",
            " limited",
            " ltd.",
            " ltd",
            " plc",
        ]:
            cleaned = cleaned.replace(suffix, "")
        tokens = [tok for tok in re.split(r"[\s,./()&-]+", cleaned) if tok and tok not in COMMON_COMPANY_WORDS]
        if tokens:
            terms.append(" ".join(tokens[:3]))
            terms.extend(tok for tok in tokens[:3] if len(tok) >= 4)
    return list(dict.fromkeys(term.strip().lower() for term in terms if term.strip()))


def text_contains_term(text: str, term: str) -> bool:
    words = re.split(r"\s+", term.strip().lower())
    if not words:
        return False
    pattern = r"\s+".join(re.escape(word) for word in words)
    return bool(re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text))


def yahoo_item_is_relevant(ticker: str, title: str, summary: str = "", company_name: str = "") -> bool:
    text = f"{title} {summary}".lower()
    if any(term in text for term in YAHOO_EXCLUDE_TERMS.get(ticker.upper(), [])):
        return False
    ticker_pattern = rf"(?<![a-z0-9]){re.escape(ticker.lower())}(?![a-z0-9])"
    if re.search(ticker_pattern, text):
        return True
    return any(text_contains_term(text, term) for term in normalized_company_terms(ticker, company_name))


def yahoo_item_title_matches(ticker: str, title: str, company_name: str = "") -> bool:
    return yahoo_item_is_relevant(ticker, title, "", company_name)


def fetch_yahoo_rss(ticker: str, now_utc: datetime, max_items: int = 5, company_name: str = "") -> list[Catalyst]:
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?" + urllib.parse.urlencode(
        {"s": ticker, "region": "US", "lang": "en-US"}
    )
    try:
        xml_text = http_get(url, timeout=15)
    except Exception:
        return []
    catalysts: list[Catalyst] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for item in root.findall(".//item")[: max_items * 3]:
        title = html.unescape((item.findtext("title") or "").strip())
        summary = html.unescape((item.findtext("description") or "").strip())
        link = item.findtext("link") or ""
        pub = parse_pubdate(item.findtext("pubDate"))
        source = item.findtext("{http://search.yahoo.com/mrss/}credit") or "Yahoo Finance RSS"
        if not title:
            continue
        if not yahoo_item_is_relevant(ticker, title, summary, company_name):
            continue
        catalyst_type, trust = classify_catalyst(title, source, summary)
        is_new = bool(pub and (now_utc - pub).total_seconds() <= 24 * 3600)
        catalysts.append(
            Catalyst(
                ticker=ticker,
                title=title,
                source=source,
                url=link,
                published_at=pub,
                catalyst_type=catalyst_type,
                trust_level=trust,
                is_new=is_new,
                raw={"summary": summary, "match_in_title": yahoo_item_title_matches(ticker, title, company_name)},
            )
        )
        if len(catalysts) >= max_items:
            break
    return catalysts


def fetch_sec_filings(ticker: str, now_utc: datetime, max_items: int = 4) -> list[Catalyst]:
    cik = cik_for_ticker(ticker)
    if not cik:
        return []
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        data = http_json(url, headers={"User-Agent": USER_AGENT})
    except Exception:
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    catalysts: list[Catalyst] = []
    for form, filing_date, accession, doc in zip(forms, filing_dates, accession_numbers, primary_docs):
        if form not in SEC_FORMS:
            continue
        try:
            filed_dt = datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
        except Exception:
            filed_dt = None
        accession_clean = accession.replace("-", "")
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{doc}" if accession and doc else ""
        title = f"{ticker} SEC filing: {form} filed {filing_date}"
        is_new = bool(filed_dt and (now_utc - filed_dt).total_seconds() <= 7 * 86400)
        catalysts.append(
            Catalyst(
                ticker=ticker,
                title=title,
                source="SEC EDGAR",
                url=filing_url,
                published_at=filed_dt,
                catalyst_type="SEC",
                trust_level="high",
                is_new=is_new,
                raw={"form": form, "filing_date": filing_date},
            )
        )
        if len(catalysts) >= max_items:
            break
    return catalysts


def catalysts_for_ticker(ticker: str, now_utc: datetime, max_items: int = 6, company_name: str = "") -> list[Catalyst]:
    if ticker in {"GOLD_BASKET"} or ticker.startswith("^") or "=" in ticker:
        return []
    found = fetch_yahoo_rss(ticker, now_utc, max_items=max_items, company_name=company_name)
    found.extend(fetch_sec_filings(ticker, now_utc, max_items=3))
    found.sort(key=lambda c: c.published_at or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return found[:max_items]


def catalyst_to_dict(c: Catalyst) -> dict:
    return {
        "ticker": c.ticker,
        "title": c.title,
        "source": c.source,
        "url": c.url,
        "published_at": c.published_at.isoformat() if c.published_at else None,
        "catalyst_type": c.catalyst_type,
        "trust_level": c.trust_level,
        "is_new": c.is_new,
        "raw": c.raw,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan Yahoo RSS and SEC filings for watchlist catalysts.")
    parser.add_argument("--symbols", nargs="*", help="Optional ticker override")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    args = parser.parse_args(argv)

    now_utc = datetime.now(timezone.utc)
    watch_items, _ = parse_watchlist_config()
    symbols = args.symbols or [item.ticker for item in watch_items if item.ticker != "GOLD_BASKET" and item.quote_enabled]
    output = {symbol: [catalyst_to_dict(c) for c in catalysts_for_ticker(symbol.upper(), now_utc)] for symbol in symbols}

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    bj = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    print(f"# 北斗新闻/SEC催化扫描\n\n扫描时间：北京时间 {bj:%Y-%m-%d %H:%M}\n")
    for symbol, catalysts in output.items():
        if not catalysts:
            continue
        print(f"## {symbol}")
        for c in catalysts[:3]:
            print(f"- {c['catalyst_type']} | {c['source']} | {c['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
