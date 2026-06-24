from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .event_schema import BeidouEvent, parse_dt

MATERIAL_UPDATE_TAGS = {
    "new_official_file",
    "new_guidance",
    "new_order",
    "new_rating",
    "new_price_confirmation",
    "new_volume_confirmation",
}


def event_signature(event: BeidouEvent) -> str:
    published = parse_dt(event.published_time).replace(second=0, microsecond=0).isoformat()
    person = event.company_person.lower().strip() or event.subject_key.lower()
    return "|".join(
        [
            event.subject_key.upper(),
            person,
            event.event_type.lower(),
            event.source.lower().strip(),
            published,
        ]
    )


def cluster_signature(event: BeidouEvent) -> str:
    person = event.company_person.lower().strip() or event.subject_key.lower()
    return "|".join([event.subject_key.upper(), person, event.event_type.lower()])


def has_material_update(event: BeidouEvent) -> bool:
    tags = {tag.lower().strip() for tag in event.tags}
    return bool(tags & MATERIAL_UPDATE_TAGS) or event.volume_confirmation


@dataclass
class DedupeStore:
    window: timedelta = timedelta(hours=48)
    seen: dict[str, datetime] = field(default_factory=dict)
    clusters: dict[str, datetime] = field(default_factory=dict)

    def is_duplicate(self, event: BeidouEvent, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        self.prune(now)
        sig = event_signature(event)
        cluster = cluster_signature(event)
        if has_material_update(event):
            return False
        exact_seen = sig in self.seen and now - self.seen[sig] <= self.window
        cluster_seen = cluster in self.clusters and now - self.clusters[cluster] <= self.window
        return exact_seen or cluster_seen

    def record(self, event: BeidouEvent) -> str:
        ts = parse_dt(event.published_time)
        sig = event_signature(event)
        self.seen[sig] = ts
        self.clusters[cluster_signature(event)] = ts
        return sig

    def accept(self, event: BeidouEvent, now: datetime | None = None) -> bool:
        if self.is_duplicate(event, now=now):
            return False
        self.record(event)
        return True

    def prune(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.seen = {key: ts for key, ts in self.seen.items() if now - ts <= self.window}
        self.clusters = {key: ts for key, ts in self.clusters.items() if now - ts <= self.window}
