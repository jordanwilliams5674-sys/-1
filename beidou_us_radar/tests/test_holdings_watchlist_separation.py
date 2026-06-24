from __future__ import annotations

import unittest
from datetime import datetime, timezone

from beidou_us_radar.core.alert_classifier import classify_event, classify_position_scope
from beidou_us_radar.core.event_schema import BeidouEvent


class HoldingsWatchlistSeparationTest(unittest.TestCase):
    def test_empty_actual_holdings_uses_watchlist_scope(self) -> None:
        event = BeidouEvent(ticker="MRVL", event_type="SEC filing", source="SEC EDGAR")
        scope = classify_position_scope(event, set(), {"MRVL", "WDC"})
        self.assertEqual(scope, "watchlist")

    def test_watchlist_and_excluded_are_separate(self) -> None:
        watch_event = BeidouEvent(ticker="WDC", event_type="guidance", source="Company IR")
        excluded_event = BeidouEvent(ticker="TSLA", event_type="guidance", source="Company IR")
        self.assertEqual(classify_position_scope(watch_event, set(), {"WDC"}), "watchlist")
        self.assertEqual(classify_position_scope(excluded_event, set(), {"WDC"}), "excluded")

    def test_social_only_event_does_not_trigger_trade_alert(self) -> None:
        event = BeidouEvent(
            ticker="WDC",
            event_type="unusual price/volume/options",
            title="Social rumor",
            source="X",
            published_time=datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
            source_kind="social",
            only_social=True,
        )
        decision = classify_event(event, actual_holdings=set(), watchlist={"WDC"})
        self.assertFalse(decision.can_trigger_trade_alert)
        self.assertEqual(decision.action, "只看")


if __name__ == "__main__":
    unittest.main()
