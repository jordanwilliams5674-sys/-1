from __future__ import annotations

import unittest
from unittest.mock import patch

from beidou_us_radar.providers.readonly_market_data import (
    assert_read_only_url,
    fetch_alpaca_latest_quotes,
    fetch_readonly_quotes,
    parse_alpaca_latest_quote,
)


class ReadOnlyMarketDataTest(unittest.TestCase):
    def test_blocks_account_order_and_transfer_paths(self) -> None:
        blocked = [
            "https://paper-api.alpaca.markets/v2/orders",
            "https://paper-api.alpaca.markets/v2/account",
            "https://paper-api.alpaca.markets/v2/positions/NVDA",
            "https://broker.example.com/v1/transfer",
        ]
        for url in blocked:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    assert_read_only_url(url)

    def test_allows_market_data_latest_quote_path(self) -> None:
        assert_read_only_url("https://data.alpaca.markets/v2/stocks/quotes/latest?symbols=NVDA&feed=iex")

    def test_parse_alpaca_quote_mid_price(self) -> None:
        quote = parse_alpaca_latest_quote("NVDA", {"bp": 120.0, "ap": 121.0, "bs": 2, "as": 3, "t": "2026-06-29T13:30:00Z"})
        self.assertEqual(quote.symbol, "NVDA")
        self.assertEqual(quote.provider, "alpaca")
        self.assertEqual(quote.price, 120.5)
        self.assertEqual(quote.bid_size, 2)
        self.assertEqual(quote.ask_size, 3)

    @patch.dict("os.environ", {}, clear=True)
    def test_alpaca_skips_without_keys(self) -> None:
        self.assertEqual(fetch_alpaca_latest_quotes(["NVDA"]), {})
        self.assertEqual(fetch_readonly_quotes(["NVDA"]), {})

    @patch.dict("os.environ", {"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"}, clear=True)
    @patch("beidou_us_radar.providers.readonly_market_data.http_json_readonly")
    def test_alpaca_latest_quotes_uses_market_data_only(self, mock_http) -> None:
        mock_http.return_value = {"quotes": {"NVDA": {"bp": 120.0, "ap": 121.0, "t": "2026-06-29T13:30:00Z"}}}
        quotes = fetch_alpaca_latest_quotes(["NVDA"])
        self.assertIn("NVDA", quotes)
        called_url = mock_http.call_args.args[0]
        self.assertIn("data.alpaca.markets/v2/stocks/quotes/latest", called_url)
        self.assertIn("feed=iex", called_url)
        self.assertNotIn("orders", called_url)
        self.assertNotIn("account", called_url)


if __name__ == "__main__":
    unittest.main()
