from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.memory.types import MemoryConsumer, MemoryReport, SystemMemory
from diskdoctor.storage.filesystem import FilesystemStorage
from diskdoctor.storage.sqlite import SQLiteStorage
from diskdoctor.types import Entry, Report, Risk, SnapshotKind


def _report(ts: datetime, *, kind: SnapshotKind = SnapshotKind.MANUAL) -> Report:
    entries = (
        []
        if kind == SnapshotKind.AUTO
        else [
            Entry(
                provider="p",
                id="p-1",
                path=Path("/tmp/x"),
                label="/tmp/x",
                size_bytes=456,
                mtime=None,
                risk=Risk.SAFE,
                recipe=[],
            )
        ]
    )
    return Report(
        entries=entries,
        scanned_at=ts,
        hostname="h",
        platform="darwin",
        kind=kind,
    )


def test_sqlite_storage_initializes_schema(tmp_path: Path) -> None:
    db = tmp_path / "devdoctor.sqlite3"

    SQLiteStorage(db)

    assert db.is_file()


def test_sqlite_storage_snapshot_round_trip(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "devdoctor.sqlite3")
    ts = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    stored = storage.write_disk_snapshot(_report(ts))

    assert stored.name == "2026-05-04T12-00-00--manual.json"
    assert stored.path.startswith("sqlite://")
    assert storage.load_disk_snapshot(stored.name).scanned_at == ts
    listed = storage.list_disk_snapshots()
    assert listed[0].name == stored.name
    assert listed[0].total_bytes == 456


def test_sqlite_storage_disk_dashboard_summary_round_trip(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "devdoctor.sqlite3")
    ts = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    storage.write_disk_dashboard_summary(_report(ts))
    summary = storage.load_disk_dashboard_summary()

    assert summary is not None
    assert summary.scanned_at == ts.isoformat()
    assert summary.total_bytes == 456
    assert summary.entry_count == 1
    assert summary.entries[0].provider == "p"
    assert summary.provider_totals[0].bytes == 456


def test_sqlite_storage_prunes_auto_snapshots(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "devdoctor.sqlite3")
    for second in range(4):
        storage.write_disk_snapshot(
            _report(
                datetime(2026, 5, 4, 12, 0, second, tzinfo=UTC),
                kind=SnapshotKind.AUTO,
            )
        )

    deleted = storage.prune_auto_disk_snapshots(keep=2)

    assert len(deleted) == 2
    assert len(storage.list_disk_snapshots(kind=SnapshotKind.AUTO)) == 2


def test_sqlite_storage_imports_filesystem_records(tmp_path: Path) -> None:
    fs = FilesystemStorage(data_dir=tmp_path / "data")
    fs.write_disk_snapshot(_report(datetime(2026, 5, 4, 12, 0, tzinfo=UTC)))
    fs.append_audit_event({"type": "cleanup", "job_id": "j1"})
    sqlite = SQLiteStorage(tmp_path / "devdoctor.sqlite3")

    snapshots, events = sqlite.import_filesystem(fs)

    assert snapshots == 1
    assert events == 1
    assert len(sqlite.list_disk_snapshots()) == 1
    assert sqlite.read_audit_events()[0]["job_id"] == "j1"


def test_sqlite_storage_memory_observation_round_trip(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "devdoctor.sqlite3")
    report = _memory_report()

    observation_id = storage.write_memory_observation(report, [])

    listed = storage.list_memory_observations()
    assert listed[0].id == observation_id
    assert listed[0].pressure == "warn"
    assert listed[0].top_consumer_name == "Firefox"
    loaded = storage.load_memory_observation(observation_id)
    assert loaded.report.system.available_bytes == 512


def test_sqlite_storage_memory_snapshot_round_trip(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "devdoctor.sqlite3")
    report = _memory_report()

    meta = storage.create_memory_snapshot(report, [], note="before")

    assert meta.note == "before"
    assert storage.list_memory_snapshots()[0].name == meta.name
    loaded = storage.load_memory_snapshot(meta.name)
    assert loaded.report.consumers[0].name == "Firefox"


def _memory_report() -> MemoryReport:
    return MemoryReport(
        scanned_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        hostname="h",
        platform="darwin",
        system=SystemMemory(
            total_bytes=1024,
            available_bytes=512,
            used_bytes=512,
            swap_used_bytes=128,
            compressed_bytes=64,
            pressure="warn",
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
