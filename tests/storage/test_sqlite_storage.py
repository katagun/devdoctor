from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from devdoctor.memory.types import MemoryConsumer, MemoryReport, SystemMemory
from devdoctor.storage.filesystem import FilesystemStorage
from devdoctor.storage.sqlite import (
    _MIGRATIONS,
    _SCHEMA_VERSION,
    SQLiteStorage,
)
from devdoctor.types import Entry, Report, Risk, SnapshotKind

_EXPECTED_TABLES = {
    "schema_migrations",
    "disk_snapshots",
    "audit_events",
    "dashboard_cache",
    "memory_observations",
    "memory_snapshots",
}


def _table_names(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def _recorded_versions(db: Path) -> list[int]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    finally:
        conn.close()
    return [int(row[0]) for row in rows]


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

    assert stored.name == "2026-05-04T12-00-00-000000--manual.json"
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


def test_fresh_db_reaches_latest_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "devdoctor.sqlite3"

    storage = SQLiteStorage(db)

    assert _table_names(db) >= _EXPECTED_TABLES
    assert _recorded_versions(db) == [version for version, _ in _MIGRATIONS]
    assert max(_recorded_versions(db)) == _SCHEMA_VERSION
    # Data operations work end to end on the freshly migrated DB.
    ts = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    storage.write_disk_snapshot(_report(ts))
    assert len(storage.list_disk_snapshots()) == 1


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "devdoctor.sqlite3"

    first = SQLiteStorage(db)
    first._ensure_schema()
    SQLiteStorage(db)  # second construction re-runs the migration path

    versions = _recorded_versions(db)
    assert versions == [version for version, _ in _MIGRATIONS]
    assert len(versions) == len(set(versions))  # no duplicate rows
    assert max(versions) == _SCHEMA_VERSION


def test_upgrades_older_db_without_losing_data(tmp_path: Path) -> None:
    db = tmp_path / "devdoctor.sqlite3"
    # Simulate a legacy v1 database: the disk-side tables exist and only
    # version 1 is stamped, so the memory-side migration has not been applied.
    conn = sqlite3.connect(db)
    try:
        for statement in _MIGRATIONS[0][1]:
            conn.execute(statement)
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)",
            (datetime(2026, 1, 1, tzinfo=UTC).isoformat(),),
        )
        conn.execute(
            """
            INSERT INTO disk_snapshots (
              name, kind, scanned_at, hostname, platform, note, total_bytes,
              duration_ms, entry_count, per_provider_json, report_json
            ) VALUES ('legacy.json', 'manual', ?, 'h', 'darwin', NULL, 10,
                      NULL, NULL, NULL, '{}')
            """,
            (datetime(2026, 1, 1, tzinfo=UTC).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()
    assert "memory_snapshots" not in _table_names(db)

    SQLiteStorage(db)

    assert _table_names(db) >= _EXPECTED_TABLES
    assert max(_recorded_versions(db)) == _SCHEMA_VERSION
    # The pre-existing row survived the upgrade.
    survived = (
        sqlite3.connect(db)
        .execute("SELECT name FROM disk_snapshots WHERE name = 'legacy.json'")
        .fetchone()
    )
    assert survived is not None


def test_converges_when_tables_present_but_unstamped(tmp_path: Path) -> None:
    # A production DB that already holds the current tables but whose
    # schema_migrations is empty (mis-stamped / version 0) must converge via
    # IF NOT EXISTS without destroying data.
    db = tmp_path / "devdoctor.sqlite3"
    seeded = SQLiteStorage(db)
    seeded.write_disk_snapshot(_report(datetime(2026, 5, 4, 12, 0, tzinfo=UTC)))
    conn = sqlite3.connect(db)
    try:
        conn.execute("DELETE FROM schema_migrations")
        conn.commit()
    finally:
        conn.close()
    assert _recorded_versions(db) == []

    SQLiteStorage(db)  # re-run the runner against the unstamped DB

    assert max(_recorded_versions(db)) == _SCHEMA_VERSION
    assert len(SQLiteStorage(db).list_disk_snapshots()) == 1


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
