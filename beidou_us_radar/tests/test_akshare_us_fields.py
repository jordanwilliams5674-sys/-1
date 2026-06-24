from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from beidou_us_radar.providers.akshare_us import SPOT_REQUIRED_FIELDS, validate_akshare_payload


class AkshareFieldsTest(unittest.TestCase):
    def test_missing_required_fields_are_stale(self) -> None:
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        result = validate_akshare_payload(
            {"symbol": "AAPL", "price": 200, "timestamp": now.isoformat()},
            required_fields=SPOT_REQUIRED_FIELDS,
            now=now,
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.staleness_flag)
        self.assertIn("change_percent", result.missing_fields)

    def test_old_akshare_timestamp_is_stale(self) -> None:
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        old = now - timedelta(hours=3)
        result = validate_akshare_payload(
            {"symbol": "AAPL", "price": 200, "change_percent": 1.2, "timestamp": old.isoformat()},
            required_fields=SPOT_REQUIRED_FIELDS,
            now=now,
            max_age=timedelta(minutes=15),
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.staleness_flag)


if __name__ == "__main__":
    unittest.main()
