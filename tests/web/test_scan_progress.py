from __future__ import annotations

import threading

from devdoctor.discovery import ProviderFinished, ProviderStarted, ScanStarted
from devdoctor.types import ProviderTiming
from devdoctor.web.scan_progress import ScanProgressHub


def _timing(name: str, entries: int, size: int, duration_ms: int = 7) -> ProviderTiming:
    return ProviderTiming(name=name, bytes=size, entries=entries, duration_ms=duration_ms)


def test_idle_hub_snapshot() -> None:
    hub = ScanProgressHub()
    snap = hub.snapshot()
    assert (snap.scan_id, snap.status, snap.total, snap.done) == (0, "idle", 0, 0)
    assert snap.started_at is None
    assert snap.providers == ()
    assert hub.version == 0


def test_snapshot_follows_a_scan_through_to_done() -> None:
    hub = ScanProgressHub()
    report = hub.observer()

    report(ScanStarted(providers=("a", "b")))
    snap = hub.snapshot()
    assert (snap.scan_id, snap.status, snap.total, snap.done) == (1, "running", 2, 0)
    assert snap.started_at is not None
    assert [p.status for p in snap.providers] == ["pending", "pending"]
    assert hub.version == 1

    report(ProviderStarted("b"))
    snap = hub.snapshot()
    assert snap.running == ("b",)
    assert {p.name: p.status for p in snap.providers} == {"a": "pending", "b": "running"}

    report(ProviderFinished(_timing("b", entries=3, size=300)))
    snap = hub.snapshot()
    assert (snap.done, snap.entries, snap.bytes, snap.running) == (1, 3, 300, ())
    b = {p.name: p for p in snap.providers}["b"]
    assert (b.status, b.duration_ms, b.entries, b.bytes) == ("done", 7, 3, 300)
    assert snap.status == "running"

    report(ProviderStarted("a"))
    report(ProviderFinished(_timing("a", entries=1, size=50)))
    snap = hub.snapshot()
    assert (snap.status, snap.done, snap.entries, snap.bytes) == ("done", 2, 4, 350)
    assert hub.version == 5


def test_events_from_an_older_scan_are_ignored() -> None:
    hub = ScanProgressHub()
    first = hub.observer()
    second = hub.observer()
    first(ScanStarted(providers=("a",)))
    second(ScanStarted(providers=("x", "y")))
    version = hub.version

    first(ProviderStarted("a"))
    first(ProviderFinished(_timing("a", entries=9, size=900)))

    snap = hub.snapshot()
    assert snap.scan_id == 2
    assert (snap.total, snap.done, snap.entries) == (2, 0, 0)
    assert hub.version == version


def test_an_empty_scan_is_done_at_once() -> None:
    hub = ScanProgressHub()
    hub.observer()(ScanStarted(providers=()))
    snap = hub.snapshot()
    assert (snap.status, snap.total, snap.done) == ("done", 0, 0)


def test_unknown_provider_events_are_ignored() -> None:
    hub = ScanProgressHub()
    report = hub.observer()
    report(ScanStarted(providers=("a",)))
    report(ProviderStarted("ghost"))
    report(ProviderFinished(_timing("ghost", entries=1, size=1)))
    snap = hub.snapshot()
    assert (snap.done, snap.entries, snap.running) == (0, 0, ())


def test_concurrent_events_keep_totals_consistent() -> None:
    hub = ScanProgressHub()
    report = hub.observer()
    names = tuple(f"p{i}" for i in range(16))
    report(ScanStarted(providers=names))

    def run(name: str, size: int) -> None:
        report(ProviderStarted(name))
        report(ProviderFinished(_timing(name, entries=1, size=size)))

    threads = [threading.Thread(target=run, args=(n, i * 10)) for i, n in enumerate(names)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = hub.snapshot()
    assert (snap.status, snap.done, snap.entries) == ("done", 16, 16)
    assert snap.bytes == sum(i * 10 for i in range(16))
    assert hub.version == 1 + 2 * 16


def test_current_reads_version_and_snapshot_together() -> None:
    hub = ScanProgressHub()
    hub.observer()(ScanStarted(providers=("a",)))
    version, snap = hub.current()
    assert version == 1 and snap.status == "running"


def test_to_json_uses_the_documented_field_names() -> None:
    hub = ScanProgressHub()
    report = hub.observer()
    report(ScanStarted(providers=("a",)))
    report(ProviderStarted("a"))
    payload = hub.snapshot().to_json()
    assert set(payload) == {
        "scan_id",
        "status",
        "started_at",
        "total",
        "done",
        "running",
        "entries",
        "bytes",
        "providers",
    }
    assert payload["running"] == ["a"]
    assert payload["started_at"].endswith("+00:00")
    assert payload["providers"] == [
        {"name": "a", "status": "running", "duration_ms": None, "entries": 0, "bytes": 0}
    ]
