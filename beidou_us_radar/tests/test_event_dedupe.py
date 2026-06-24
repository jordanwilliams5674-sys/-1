from __future__ import annotations

import unittest
from datetime import datetime, timezone

from beidou_us_radar.core.event_dedupe import DedupeStore
from beidou_us_radar.core.event_schema import BeidouEvent


class EventDedupeTest(unittest.TestCase):
    def test_duplicate_event_within_48_hours_is_filtered(self) -> None:
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        event = BeidouEvent(
            ticker="MRVL",
            company_person="Marvell",
            event_type="earnings",
            title="Marvell earnings reaction",
            source="CNBC",
            published_time=now,
            source_kind="reliable_news",
        )
        store = DedupeStore()
        self.assertTrue(store.accept(event, now=now))
        duplicate = BeidouEvent(
            ticker="MRVL",
            company_person="Marvell",
            event_type="earnings",
            title="Marvell earnings reaction again",
            source="CNBC",
            published_time=now,
            source_kind="reliable_news",
        )
        self.assertFalse(store.accept(duplicate, now=now))

    def test_material_update_is_not_filtered(self) -> None:
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        store = DedupeStore()
        original = BeidouEvent(
            ticker="MRVL",
            company_person="Marvell",
            event_type="guidance",
            title="Initial guidance headline",
            source="Company IR",
            published_time=now,
            source_kind="company_ir",
        )
        store.record(original)
        updated = BeidouEvent(
            ticker="MRVL",
            company_person="Marvell",
            event_type="guidance",
            title="New official guidance filed",
            source="Company IR",
            published_time=now,
            source_kind="company_ir",
            tags=["new_guidance"],
        )
        self.assertTrue(store.accept(updated, now=now))


if __name__ == "__main__":
    unittest.main()
