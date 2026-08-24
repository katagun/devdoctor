from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from diskdoctor.memory.types import MemoryReport, MemorySuggestion
from diskdoctor.types import Report, SnapshotKind


@dataclass(frozen=True)
class StoredSnapshot:
    name: str
    path: str


@dataclass(frozen=True)
class StoredSnapshotMeta:
    name: str
    path: str
    scanned_at: str
    hostname: str
    platform: str
    note: str | None
    total_bytes: int
    kind: str
    duration_ms: int | None
    entry_count: int | None
    per_provider: list[dict[str, object]] | None


@dataclass(frozen=True)
class DiskDashboardEntry:
    id: str
    provider: str
    label: str
    size_bytes: int
    risk: Literal["safe", "reclaimable", "dangerous"]


@dataclass(frozen=True)
class DiskDashboardProviderTotal:
    provider: str
    bytes: int
    count: int


@dataclass(frozen=True)
class DiskDashboardSummary:
    scanned_at: str
    hostname: str
    platform: str
    total_bytes: int
    entry_count: int
    entries: list[DiskDashboardEntry]
    provider_totals: list[DiskDashboardProviderTotal]


@dataclass(frozen=True)
class MemoryObservationMeta:
    id: str
    scanned_at: str
    pressure: str
    total_bytes: int
    available_bytes: int
    used_bytes: int
    swap_used_bytes: int | None
    compressed_bytes: int | None
    top_consumer_name: str | None
    top_consumer_kind: str | None
    top_consumer_rss_bytes: int | None
    suggestion_count: int


@dataclass(frozen=True)
class StoredMemoryObservation:
    id: str
    report: MemoryReport
    suggestions: list[MemorySuggestion]


@dataclass(frozen=True)
class MemorySnapshotMeta:
    name: str
    created_at: str
    scanned_at: str
    note: str | None
    pressure: str
    total_bytes: int
    available_bytes: int
    used_bytes: int
    top_consumer_name: str | None
    top_consumer_kind: str | None
    top_consumer_rss_bytes: int | None


@dataclass(frozen=True)
class StoredMemorySnapshot:
    name: str
    created_at: str
    note: str | None
    report: MemoryReport
    suggestions: list[MemorySuggestion]


class StorageBackend(Protocol):
    def write_disk_snapshot(self, report: Report) -> StoredSnapshot: ...

    def list_disk_snapshots(
        self,
        *,
        limit: int | None = None,
        kind: SnapshotKind | None = None,
    ) -> list[StoredSnapshotMeta]: ...

    def load_disk_snapshot(self, name: str) -> Report: ...

    def prune_auto_disk_snapshots(self, *, keep: int) -> list[str]: ...

    def write_disk_dashboard_summary(self, report: Report) -> None: ...

    def load_disk_dashboard_summary(self) -> DiskDashboardSummary | None: ...

    def append_audit_event(self, event: Mapping[str, object]) -> None: ...

    def read_audit_events(self, *, limit: int | None = None) -> list[dict[str, object]]: ...

    def write_memory_observation(
        self,
        report: MemoryReport,
        suggestions: list[MemorySuggestion],
    ) -> str: ...

    def list_memory_observations(
        self,
        *,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[MemoryObservationMeta]: ...

    def load_memory_observation(self, observation_id: str) -> StoredMemoryObservation: ...

    def latest_memory_observation(self) -> MemoryObservationMeta | None: ...

    def prune_memory_observations(self, *, keep: int) -> list[str]: ...

    def create_memory_snapshot(
        self,
        report: MemoryReport,
        suggestions: list[MemorySuggestion],
        *,
        note: str | None = None,
    ) -> MemorySnapshotMeta: ...

    def list_memory_snapshots(self, *, limit: int | None = None) -> list[MemorySnapshotMeta]: ...

    def load_memory_snapshot(self, name: str) -> StoredMemorySnapshot: ...
