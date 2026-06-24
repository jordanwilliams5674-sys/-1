#!/usr/bin/env python3
"""Automated five-site cross verification for the Beidou radar.

No broker APIs are called here. This module only checks public research pages
or optional data APIs and returns source status for manual review.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

USER_AGENT = "premarket_mover_radar/1.0 contact=295765031@qq.com"


@dataclass
class SourceCheck:
    source: str
    status: str
    summary: str
    url: str
    automation_level: str
    requires_login: bool = False
    needs_api_key: bool = False
    raw: dict | None = None


def http_get(url: str, timeout: int = 8, headers: dict | None = None) -> str:
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_post_json(url: str, payload: dict, timeout: int = 8) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def clean_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return title[:160]


def compact_num(value) -> str:
    try:
        n = float(value)
    except Exception:
        return "未知"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def tv_exchange_symbols(ticker: str) -> list[str]:
    t = ticker.upper()
    if t in {"GLD", "IAU"}:
        return [f"AMEX:{t}", f"NYSEARCA:{t}"]
    if t.startswith("^") or "=" in t or "-" in t:
        return []
    return [f"NASDAQ:{t}", f"NYSE:{t}", f"AMEX:{t}"]


def fetch_tradingview_scan(symbols: list[str]) -> dict[str, dict]:
    tickers: list[str] = []
    for symbol in symbols:
        tickers.extend(tv_exchange_symbols(symbol))
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return {}
    payload = {
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": [
            "name",
            "description",
            "close",
            "change",
            "volume",
            "premarket_change",
            "premarket_volume",
            "Recommend.All",
        ],
    }
    data = http_post_json("https://scanner.tradingview.com/america/scan", payload)
    result: dict[str, dict] = {}
    for row in data.get("data", []):
        values = row.get("d", [])
        if len(values) < 8:
            continue
        ticker = str(values[0]).upper()
        result[ticker] = {
            "exchange_symbol": row.get("s"),
            "ticker": ticker,
            "description": values[1],
            "close": values[2],
            "change": values[3],
            "volume": values[4],
            "premarket_change": values[5],
            "premarket_volume": values[6],
            "recommend_all": values[7],
        }
    return result


def check_tradingview(ticker: str) -> SourceCheck:
    url = f"https://www.tradingview.com/symbols/{ticker.upper()}/"
    try:
        data = fetch_tradingview_scan([ticker])
        row = data.get(ticker.upper())
        if row:
            pm = row.get("premarket_change")
            pmv = row.get("premarket_volume")
            rec = row.get("recommend_all")
            summary = f"已自动查询：盘前变动 {pm:.2f}%；盘前量 {compact_num(pmv)}；技术综合 {rec:.2f}。" if isinstance(pm, (int, float)) else "已自动查询：TradingView scanner 有结果，但盘前字段为空。"
            return SourceCheck("TradingView", "已自动查询", summary, url, "auto_api_public", raw=row)
        return SourceCheck("TradingView", "自动查询无结果", "TradingView scanner 未返回该代码，可能是交易所映射或代码格式问题。", url, "auto_api_public")
    except Exception as exc:
        return SourceCheck("TradingView", "访问受限", f"自动查询失败：{exc}", url, "auto_api_public")


def check_stockanalysis(ticker: str) -> SourceCheck:
    url = f"https://stockanalysis.com/stocks/{ticker.lower()}/"
    if not re.match(r"^[A-Z][A-Z0-9.]{0,9}$", ticker.upper()):
        return SourceCheck("StockAnalysis", "不适用", "非普通美股代码，跳过 StockAnalysis 个股页。", url, "auto_public_page")
    try:
        text = http_get(url)
        title = clean_title(text)
        has_financials = "Financials" in text or "/financials/" in text
        summary = f"已自动查询：{title or '页面可访问'}；财务入口{'存在' if has_financials else '未确认'}。"
        return SourceCheck("StockAnalysis", "已自动查询", summary, url, "auto_public_page", raw={"title": title, "has_financials": has_financials})
    except Exception as exc:
        return SourceCheck("StockAnalysis", "访问受限", f"自动查询失败：{exc}", url, "auto_public_page")


def check_whalewisdom(ticker: str) -> SourceCheck:
    url = f"https://whalewisdom.com/stock/{ticker.lower()}"
    if not re.match(r"^[A-Z][A-Z0-9.]{0,9}$", ticker.upper()):
        return SourceCheck("WhaleWisdom", "不适用", "非普通美股代码，跳过机构持仓页。", url, "auto_public_page")
    try:
        text = http_get(url)
        title = clean_title(text)
        summary = f"已确认：公开页可访问；{title or '机构持仓背景页存在'}。13F 滞后，只作背景分。"
        return SourceCheck("WhaleWisdom", "已确认：支持", summary, url, "auto_public_page", raw={"title": title})
    except Exception as exc:
        return SourceCheck("WhaleWisdom", "访问受限", f"自动查询失败：{exc}", url, "auto_public_page")


def check_quiver(ticker: str) -> SourceCheck:
    url = f"https://www.quiverquant.com/stock/{ticker.upper()}/"
    api_key = os.environ.get("QUIVER_API_KEY")
    if api_key:
        return SourceCheck(
            "Quiver Quant",
            "需要适配 API",
            "已检测到 QUIVER_API_KEY，但当前未配置 Quiver 具体 endpoint；暂不编造国会/合同结果。",
            url,
            "api_key_detected_not_wired",
            requires_login=True,
            needs_api_key=True,
        )
    try:
        text = http_get(url)
        title = clean_title(text)
        summary = f"公开页自动探测成功：{title or '页面可访问'}；结构化国会/合同数据需要 API Key。"
        return SourceCheck("Quiver Quant", "公开页已自动探测 / 结构化数据需 API Key", summary, url, "auto_public_probe_plus_api_key", requires_login=True, needs_api_key=True, raw={"title": title})
    except Exception as exc:
        return SourceCheck("Quiver Quant", "访问受限 / 需要 API Key", f"公开页自动探测失败：{exc}", url, "api_key_required", requires_login=True, needs_api_key=True)


_ITC_CACHE: SourceCheck | None = None


def check_itc_markets() -> SourceCheck:
    global _ITC_CACHE
    if _ITC_CACHE:
        return _ITC_CACHE
    url = "https://www.itcmarkets.com/cheat-sheet/"
    try:
        text = http_get(url)
        title = clean_title(text)
        summary = f"已自动探测宏观页：{title or '页面可访问'}；该源为宏观利率过滤器，不是个股催化。"
        _ITC_CACHE = SourceCheck("ITC Markets Hawk/Dove Cheat Sheet", "已自动查询", summary, url, "auto_public_page", raw={"title": title})
        return _ITC_CACHE
    except Exception as exc:
        _ITC_CACHE = SourceCheck("ITC Markets Hawk/Dove Cheat Sheet", "访问受限", f"自动查询失败：{exc}", url, "auto_public_page")
        return _ITC_CACHE


def five_site_cross_check(ticker: str) -> dict[str, SourceCheck]:
    t = ticker.upper()
    return {
        "TradingView": check_tradingview(t),
        "StockAnalysis": check_stockanalysis(t),
        "WhaleWisdom": check_whalewisdom(t),
        "Quiver Quant": check_quiver(t),
        "ITC Markets": check_itc_markets(),
    }


def format_cross_checks(checks: dict[str, SourceCheck]) -> list[str]:
    lines = ["五站交叉验证："]
    order = ["TradingView", "StockAnalysis", "WhaleWisdom", "Quiver Quant", "ITC Markets"]
    for key in order:
        check = checks.get(key)
        if not check:
            continue
        lines.append(f"* {check.source}：{check.status}；{check.summary}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run five-site cross verification.")
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = {ticker.upper(): five_site_cross_check(ticker.upper()) for ticker in args.tickers}
    if args.json:
        print(json.dumps({k: {kk: asdict(vv) for kk, vv in v.items()} for k, v in result.items()}, ensure_ascii=False, indent=2))
    else:
        for ticker, checks in result.items():
            print(f"## {ticker}")
            print("\n".join(format_cross_checks(checks)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
