from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
