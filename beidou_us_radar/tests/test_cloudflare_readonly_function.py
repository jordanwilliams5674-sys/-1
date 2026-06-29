from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FUNCTION_FILE = ROOT / "functions" / "api" / "quotes.js"
HTML_SOURCE = ROOT / "beidou_monitor_site" / "preview_dashboard.html"


class CloudflareReadOnlyFunctionTest(unittest.TestCase):
    def test_function_exists_and_uses_market_data_endpoint(self) -> None:
        text = FUNCTION_FILE.read_text(encoding="utf-8")
        self.assertIn("data.alpaca.markets/v2/stocks/quotes/latest", text)
        self.assertIn("onRequestGet", text)
        self.assertIn("noTrading", text)
        self.assertIn("noAccountAccess", text)
        self.assertNotIn("paper-api.alpaca.markets", text)

    def test_function_blocks_trading_related_paths(self) -> None:
        text = FUNCTION_FILE.read_text(encoding="utf-8")
        for blocked in ["account", "order", "position", "trade", "transfer", "withdraw", "deposit"]:
            self.assertIn(f'"{blocked}"', text)
        self.assertIn("Blocked non-market-data endpoint", text)

    def test_dashboard_has_optional_dynamic_quote_overlay(self) -> None:
        html = HTML_SOURCE.read_text(encoding="utf-8")
        self.assertIn("api/quotes?symbols=", html)
        self.assertIn("applyDynamicQuotes", html)
        self.assertIn("动态只读", html)
        self.assertIn("Cloudflare Functions 只读行情", html)


if __name__ == "__main__":
    unittest.main()
