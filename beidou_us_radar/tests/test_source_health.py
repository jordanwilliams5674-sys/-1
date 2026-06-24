from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from beidou_us_radar.core.source_health import check_payload_health


class SourceHealthTest(unittest.TestCase):
    def test_healthy_payload(self) -> None:
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        result = check_payload_health(
            "market_data",
            {"symbol": "AAPL", "price": 200, "timestamp": now.isoformat()},
            ["symbol", "price", "timestamp"],
            now=now,
            max_age=timedelta(minutes=10),
        )
        self.assertTrue(result.ok)
        self.assertFalse(result.staleness_flag)

    def test_missing_and_stale_payload_is_flagged(self) -> None:
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        old = now - timedelta(hours=2)
        result = check_payload_health(
            "market_data",
            {"symbol": "AAPL", "timestamp": old.isoformat()},
            ["symbol", "price", "timestamp"],
            now=now,
            max_age=timedelta(minutes=10),
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.staleness_flag)
        self.assertIn("price", result.missing_fields)


if __name__ == "__main__":
    unittest.main()
