from __future__ import annotations

import unittest
from datetime import datetime, timezone

from beidou_us_radar.core.alert_classifier import classify_event
from beidou_us_radar.core.beidou_formatter import format_mobile_alert
from beidou_us_radar.core.event_schema import BeidouEvent


class BeidouFormatterTest(unittest.TestCase):
    def test_mobile_alert_uses_beijing_and_eastern_time(self) -> None:
        event = BeidouEvent(
            ticker="MRVL",
            company_person="Marvell",
            event_type="SEC filing",
            title="Marvell files 8-K",
            description="Company filed an 8-K with SEC.",
            source="SEC EDGAR",
            published_time=datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
            collected_at=datetime(2026, 6, 6, 12, 5, tzinfo=timezone.utc),
            source_kind="sec",
            source_tier="official",
            credibility=1.0,
            raw={"duplicate": False},
        )
        decision = classify_event(event, actual_holdings={"MRVL"}, watchlist={"MU"})
        text = format_mobile_alert(event, decision, reminder_time=datetime(2026, 6, 6, 12, 5, tzinfo=timezone.utc))
        self.assertIn("北京时间 2026年06月06日 20:05", text)
        self.assertIn("美东时间 2026年06月06日 08:05", text)
        self.assertNotIn("东京", text)
        for section in ["【一句话结论】", "【事件链】", "【相关标的】", "【操作】"]:
            self.assertIn(section, text)


if __name__ == "__main__":
    unittest.main()
