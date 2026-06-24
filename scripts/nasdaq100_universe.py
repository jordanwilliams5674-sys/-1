#!/usr/bin/env python3
"""Fetch Nasdaq 100 symbols for the premarket radar universe."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "config" / "nasdaq100_symbols.txt"
USER_AGENT = "Mozilla/5.0 premarket_mover_radar/1.0"


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", ".")


def fetch_from_nasdaq_api() -> list[str]:
    url = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    rows = data.get("data", {}).get("data", {}).get("rows", [])
    symbols = [normalize_symbol(row.get("symbol", "")) for row in rows]
    return [s for s in symbols if re.match(r"^[A-Z][A-Z0-9.]{0,9}$", s)]


def fetch_from_wikipedia() -> list[str]:
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    symbols = re.findall(r"<td>\s*<a[^>]*>\s*([A-Z][A-Z0-9.]{0,9})\s*</a>\s*</td>", html)
    # Fallback table regex can overmatch, so keep a conservative unique list.
    unique = []
    for symbol in symbols:
        symbol = normalize_symbol(symbol)
        if symbol not in unique:
            unique.append(symbol)
    return unique[:110]


def read_cache(cache_path: Path = CACHE_PATH, max_age_hours: int = 24) -> list[str]:
    if not cache_path.exists():
        return []
    if time.time() - cache_path.stat().st_mtime > max_age_hours * 3600:
        return []
    symbols = [
        normalize_symbol(line)
        for line in cache_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return [s for s in symbols if re.match(r"^[A-Z][A-Z0-9.]{0,9}$", s)]


def write_cache(symbols: list[str], cache_path: Path = CACHE_PATH) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("\n".join(symbols) + "\n", encoding="utf-8")


def get_nasdaq100_symbols(cache_hours: int = 24, force_refresh: bool = False) -> list[str]:
    if not force_refresh:
        cached = read_cache(max_age_hours=cache_hours)
        if cached:
            return cached
    for fetcher in (fetch_from_nasdaq_api, fetch_from_wikipedia):
        try:
            symbols = fetcher()
        except Exception:
            continue
        if len(symbols) >= 90:
            symbols = list(dict.fromkeys(symbols))
            write_cache(symbols)
            return symbols
    cached = read_cache(max_age_hours=24 * 365)
    return cached


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Nasdaq 100 symbols.")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    symbols = get_nasdaq100_symbols(force_refresh=args.refresh)
    if args.json:
        print(json.dumps({"count": len(symbols), "symbols": symbols}, ensure_ascii=False, indent=2))
    else:
        print("\n".join(symbols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

