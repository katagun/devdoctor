"""Progress of the scan running in this server process, as a versioned snapshot.

``discovery.scan`` reports events from its worker threads through the callback
``observer()`` hands out; ``/api/scan/progress`` streams ``snapshot()`` whenever
``version`` changes. The hub never influences the scan (spec §2.4).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from devdoctor.discovery import (
    ProviderStarted,
    ScanProgressCallback,
    ScanProgressEvent,
    ScanStarted,
)

ProviderStatus = Literal["pending", "running", "done"]
ScanStatus = Literal["idle", "running", "done"]


@dataclass(frozen=True)
class ProviderProgress:
    name: str
    status: ProviderStatus
    duration_ms: int | None
    entries: int
    bytes: int


@dataclass(frozen=True)
class ScanProgressSnapshot:
    scan_id: int
    status: ScanStatus
    started_at: datetime | None
    total: int
    done: int
    running: tuple[str, ...]
    entries: int
    bytes: int
    providers: tuple[ProviderProgress, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "total": self.total,
            "done": self.done,
            "running": list(self.running),
            "entries": self.entries,
            "bytes": self.bytes,
            "providers": [
                {
                    "name": p.name,
                    "status": p.status,
                    "duration_ms": p.duration_ms,
                    "entries": p.entries,
                    "bytes": p.bytes,
                }
                for p in self.providers
            ],
        }


IDLE = ScanProgressSnapshot(
    scan_id=0,
    status="idle",
    started_at=None,
    total=0,
    done=0,
    running=(),
    entries=0,
    bytes=0,
    providers=(),
)


class ScanProgressHub:
    """Thread-safe: events arrive from the scan's worker threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = IDLE
        self._version = 0
        self._next_scan_id = 1

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> ScanProgressSnapshot:
        with self._lock:
            return self._snapshot

    def current(self) -> tuple[int, ScanProgressSnapshot]:
        """Version and snapshot read under one lock, so they always match."""
        with self._lock:
            return self._version, self._snapshot

    def observer(self) -> ScanProgressCallback:
        """A callback bound to the next scan id; older scans' events are then ignored."""
        with self._lock:
            scan_id = self._next_scan_id
            self._next_scan_id += 1

        def on_progress(event: ScanProgressEvent) -> None:
            self._apply(scan_id, event)

        return on_progress

    def _apply(self, scan_id: int, event: ScanProgressEvent) -> None:
        with self._lock:
            if scan_id < self._snapshot.scan_id:
                return
            if isinstance(event, ScanStarted):
                providers = tuple(
                    ProviderProgress(name, "pending", None, 0, 0) for name in event.providers
                )
                self._snapshot = _rebuild(scan_id, datetime.now(UTC), providers)
            elif scan_id != self._snapshot.scan_id:
                # A provider event before its ScanStarted, or from an unknown scan.
                return
            elif isinstance(event, ProviderStarted):
                self._snapshot = _update(self._snapshot, event.name, status="running")
            else:
                timing = event.timing
                self._snapshot = _update(
                    self._snapshot,
                    timing.name,
                    status="done",
                    duration_ms=timing.duration_ms,
                    entries=timing.entries,
                    bytes=timing.bytes,
                )
            self._version += 1


def _update(snapshot: ScanProgressSnapshot, name: str, **changes: Any) -> ScanProgressSnapshot:
    providers = tuple(replace(p, **changes) if p.name == name else p for p in snapshot.providers)
    return _rebuild(snapshot.scan_id, snapshot.started_at, providers)


def _rebuild(
    scan_id: int, started_at: datetime | None, providers: tuple[ProviderProgress, ...]
) -> ScanProgressSnapshot:
    done = [p for p in providers if p.status == "done"]
    return ScanProgressSnapshot(
        scan_id=scan_id,
        status="done" if len(done) == len(providers) else "running",
        started_at=started_at,
        total=len(providers),
        done=len(done),
        running=tuple(p.name for p in providers if p.status == "running"),
        entries=sum(p.entries for p in done),
        bytes=sum(p.bytes for p in done),
        providers=providers,
    )
