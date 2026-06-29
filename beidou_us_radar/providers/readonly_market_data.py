from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


FORBIDDEN_ACTION_WORDS = {
    "order",
    "orders",
    "trade",
    "trading",
    "account",
    "accounts",
    "position",
    "positions",
    "transfer",
    "withdraw",
    "deposit",
}


@dataclass(frozen=True)
class ReadOnlyQuote:
    symbol: str
    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    timestamp: str | None = None
    source: str = ""
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def assert_read_only_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    path_parts = {part.lower() for part in parsed.path.split("/") if part}
    blocked = path_parts & FORBIDDEN_ACTION_WORDS
    if blocked:
        raise ValueError(f"Refusing non-market-data endpoint: {sorted(blocked)}")


def http_json_readonly(url: str, headers: dict[str, str] | None = None, timeout: int = 8) -> dict[str, Any]:
    assert_read_only_url(url)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "beidou-readonly-market-data/1.0",
            **(headers or {}),
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def alpaca_headers_from_env() -> dict[str, str] | None:
    key_id = os.environ.get("ALPACA_KEY_ID")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not key_id or not secret_key:
        return None
    return {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
    }


def parse_alpaca_latest_quote(symbol: str, row: dict[str, Any]) -> ReadOnlyQuote:
    quote = row.get("q") if isinstance(row.get("q"), dict) else row
    bid = safe_float(quote.get("bp"))
    ask = safe_float(quote.get("ap"))
    price = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        price = (bid + ask) / 2
    elif ask is not None:
        price = ask
    elif bid is not None:
        price = bid
    return ReadOnlyQuote(
        symbol=symbol.upper(),
        price=price,
        bid=bid,
        ask=ask,
        bid_size=safe_int(quote.get("bs")),
        ask_size=safe_int(quote.get("as")),
        timestamp=str(quote.get("t") or datetime.now(timezone.utc).isoformat()),
        source="Alpaca Market Data latest quotes",
        provider="alpaca",
        raw=quote,
    )


def fetch_alpaca_latest_quotes(symbols: list[str], feed: str = "iex") -> dict[str, ReadOnlyQuote]:
    headers = alpaca_headers_from_env()
    clean_symbols = [symbol.upper().strip() for symbol in symbols if symbol and symbol.strip()]
    if not headers or not clean_symbols:
        return {}
    url = "https://data.alpaca.markets/v2/stocks/quotes/latest?" + urllib.parse.urlencode(
        {"symbols": ",".join(clean_symbols), "feed": feed}
    )
    data = http_json_readonly(url, headers=headers)
    quotes = data.get("quotes") or {}
    out: dict[str, ReadOnlyQuote] = {}
    if isinstance(quotes, dict):
        for symbol, row in quotes.items():
            if isinstance(row, dict):
                parsed = parse_alpaca_latest_quote(symbol, row)
                out[parsed.symbol] = parsed
    return out


def fetch_readonly_quotes(symbols: list[str], providers: list[str] | None = None) -> dict[str, ReadOnlyQuote]:
    providers = providers or ["alpaca"]
    out: dict[str, ReadOnlyQuote] = {}
    if "alpaca" in providers:
        out.update(fetch_alpaca_latest_quotes(symbols))
    return out
