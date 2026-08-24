from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from diskdoctor.memory.types import MemoryConsumer, MemoryReport, SystemMemory
from diskdoctor.storage.filesystem import FilesystemStorage
from diskdoctor.types import Entry, Report, Risk, SnapshotKind


def _report(ts: datetime, *, kind: SnapshotKind = SnapshotKind.MANUAL) -> Report:
    return Report(
        entries=[
            Entry(
                provider="p",
                id="p-1",
                path=Path("/tmp/x"),
                label="/tmp/x",
                size_bytes=123,
                mtime=None,
                risk=Risk.SAFE,
                recipe=[],
            )
        ],
        scanned_at=ts,
        hostname="h",
        platform="darwin",
        kind=kind,
    )


def test_filesystem_storage_writes_existing_snapshot_format(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)
    ts = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    stored = storage.write_disk_snapshot(_report(ts))

    path = tmp_path / "snapshots" / stored.name
    assert stored.path == str(path)
    assert path.is_file()
    assert '"schema_version": 2' in path.read_text()
    assert storage.load_disk_snapshot(stored.name).total_bytes() == 123


def test_filesystem_storage_reads_and_filters_snapshots(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)
    storage.write_disk_snapshot(_report(datetime(2026, 5, 4, 12, 0, tzinfo=UTC)))
    storage.write_disk_snapshot(
        _report(datetime(2026, 5, 4, 12, 1, tzinfo=UTC), kind=SnapshotKind.AUTO)
    )

    autos = storage.list_disk_snapshots(kind=SnapshotKind.AUTO)

    assert len(autos) == 1
    assert autos[0].kind == "auto"


def test_filesystem_storage_disk_dashboard_summary_round_trip(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)
    ts = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    storage.write_disk_dashboard_summary(_report(ts))
    summary = storage.load_disk_dashboard_summary()

    assert summary is not None
    assert summary.scanned_at == ts.isoformat()
    assert summary.total_bytes == 123
    assert summary.entry_count == 1
    assert summary.entries[0].label == "/tmp/x"
    assert summary.provider_totals[0].provider == "p"


def test_filesystem_storage_audit_round_trip(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)

    storage.append_audit_event({"type": "cleanup", "job_id": "j1"})

    events = storage.read_audit_events()
    assert len(events) == 1
    assert events[0]["type"] == "cleanup"
    assert events[0]["job_id"] == "j1"
    assert (tmp_path / "audit.jsonl").is_file()


def test_filesystem_storage_memory_observation_round_trip(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)

    observation_id = storage.write_memory_observation(_memory_report(), [])

    assert storage.list_memory_observations()[0].id == observation_id
    loaded = storage.load_memory_observation(observation_id)
    assert loaded.report.consumers[0].name == "Firefox"


def test_filesystem_storage_memory_snapshot_round_trip(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)

    meta = storage.create_memory_snapshot(_memory_report(), [], note="before")

    assert storage.list_memory_snapshots()[0].name == meta.name
    assert storage.load_memory_snapshot(meta.name).note == "before"


@pytest.mark.parametrize(
    "name",
    [
        "../../../../etc/passwd",
        "..",
        "sub/dir",
        "/etc/passwd",
        "",
    ],
)
def test_load_disk_snapshot_rejects_traversal(tmp_path: Path, name: str) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)
    # A traversal name must be indistinguishable from a missing snapshot,
    # never a read outside the snapshots directory.
    with pytest.raises(FileNotFoundError):
        storage.load_disk_snapshot(name)


@pytest.mark.parametrize("name", ["../../../../etc/passwd", "..", "sub/dir", "/etc/passwd", ""])
def test_load_memory_snapshot_rejects_traversal(tmp_path: Path, name: str) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        storage.load_memory_snapshot(name)


def test_latest_memory_observation_returns_newest(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)
    assert storage.latest_memory_observation() is None

    base = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    for i, pressure in enumerate(["ok", "warn", "critical"]):
        storage.write_memory_observation(
            _memory_report(scanned_at=base.replace(second=i), pressure=pressure), []
        )

    latest = storage.latest_memory_observation()
    assert latest is not None
    assert latest.pressure == "critical"  # the last one appended
    assert latest.scanned_at == base.replace(second=2).isoformat()


def test_prune_memory_observations_amortizes_rewrites(tmp_path: Path, monkeypatch) -> None:
    # Shrink the slack so the test doesn't need hundreds of writes to trip it.
    monkeypatch.setattr("diskdoctor.storage.filesystem._PRUNE_SLACK", 2)
    storage = FilesystemStorage(data_dir=tmp_path)
    base = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    # keep=2, slack=2 → nothing is rewritten until there are > 4 observations.
    for i in range(4):
        storage.write_memory_observation(_memory_report(scanned_at=base.replace(second=i)), [])
    assert storage.prune_memory_observations(keep=2) == []  # under the gate

    for i in range(4, 6):
        storage.write_memory_observation(_memory_report(scanned_at=base.replace(second=i)), [])
    victims = storage.prune_memory_observations(keep=2)  # 6 > 2 + 2 → now prune
    assert len(victims) == 4
    assert len(storage.list_memory_observations()) == 2


def test_same_second_snapshots_do_not_clobber(tmp_path: Path) -> None:
    storage = FilesystemStorage(data_dir=tmp_path)
    ts = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
    storage.write_disk_snapshot(_report(ts.replace(microsecond=1)))
    storage.write_disk_snapshot(_report(ts.replace(microsecond=2)))
    # Both must survive — microsecond precision keeps their filenames distinct.
    assert len(storage.list_disk_snapshots()) == 2


def _memory_report(
    *,
    scanned_at: datetime | None = None,
    pressure: str = "warn",
) -> MemoryReport:
    return MemoryReport(
        scanned_at=scanned_at or datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        hostname="h",
        platform="darwin",
        system=SystemMemory(
            total_bytes=1024,
            available_bytes=512,
            used_bytes=512,
            swap_used_bytes=128,
            compressed_bytes=64,
            pressure=pressure,
        ),
        consumers=[
            MemoryConsumer(
                id="pid:1",
                pid=1,
                parent_pid=0,
                name="Firefox",
                kind="browser",
                rss_bytes=256,
                private_bytes=None,
                command="firefox",
            )
        ],
    )
