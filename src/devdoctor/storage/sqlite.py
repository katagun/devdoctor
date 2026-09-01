from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from devdoctor import history_log
from devdoctor.dashboard import (
    build_disk_dashboard_summary,
    disk_dashboard_summary_from_dict,
    disk_dashboard_summary_to_dict,
)
from devdoctor.memory import serde as memory_serde
from devdoctor.memory.types import MemoryReport, MemorySuggestion
from devdoctor.storage.base import (
    DiskDashboardSummary,
    MemoryObservationMeta,
    MemorySnapshotMeta,
    StoredMemoryObservation,
    StoredMemorySnapshot,
    StoredSnapshot,
    StoredSnapshotMeta,
)
from devdoctor.storage.filesystem import (
    FilesystemStorage,
    _memory_observation_meta,
    _memory_snapshot_meta,
)
from devdoctor.types import Report, SnapshotKind

# Bookkeeping table for the migration runner. Created before any migration so
# that _current_schema_version can read the recorded version. It is intentionally
# NOT part of a numbered migration.
_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
)
"""

# Each migration is (target_version, statements) where the statements bring the
# database from target_version - 1 to target_version. Every statement uses
# IF NOT EXISTS semantics so a migration is safe to (re)run against a database
# that already holds the objects it creates — an existing production DB whose
# tables are present but whose schema_migrations rows are missing/behind
# converges without touching or dropping any data. To add a schema change later,
# append a new (N, statements) tuple; _SCHEMA_VERSION picks it up automatically.

# Migration 1 (baseline): the original disk-side schema.
_MIGRATION_1_DISK = (
    """
    CREATE TABLE IF NOT EXISTS disk_snapshots (
      name TEXT PRIMARY KEY,
      kind TEXT NOT NULL,
      scanned_at TEXT NOT NULL,
      hostname TEXT NOT NULL,
      platform TEXT NOT NULL,
      note TEXT,
      total_bytes INTEGER NOT NULL,
      duration_ms INTEGER,
      entry_count INTEGER,
      per_provider_json TEXT,
      report_json TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_disk_snapshots_kind_scanned_at
      ON disk_snapshots(kind, scanned_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      at TEXT NOT NULL,
      type TEXT NOT NULL,
      payload_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_events_at ON audit_events(at DESC)",
    """
    CREATE TABLE IF NOT EXISTS dashboard_cache (
      key TEXT PRIMARY KEY,
      updated_at TEXT NOT NULL,
      payload_json TEXT NOT NULL
    )
    """,
)

# Migration 2: the memory-side tables added after the disk baseline.
_MIGRATION_2_MEMORY = (
    """
    CREATE TABLE IF NOT EXISTS memory_observations (
      id TEXT PRIMARY KEY,
      scanned_at TEXT NOT NULL,
      pressure TEXT NOT NULL,
      total_bytes INTEGER NOT NULL,
      available_bytes INTEGER NOT NULL,
      used_bytes INTEGER NOT NULL,
      swap_used_bytes INTEGER,
      compressed_bytes INTEGER,
      top_consumer_name TEXT,
      top_consumer_kind TEXT,
      top_consumer_rss_bytes INTEGER,
      suggestion_count INTEGER NOT NULL,
      report_json TEXT NOT NULL,
      suggestions_json TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_observations_scanned_at
      ON memory_observations(scanned_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_observations_pressure_scanned_at
      ON memory_observations(pressure, scanned_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_snapshots (
      name TEXT PRIMARY KEY,
      created_at TEXT NOT NULL,
      scanned_at TEXT NOT NULL,
      note TEXT,
      pressure TEXT NOT NULL,
      total_bytes INTEGER NOT NULL,
      available_bytes INTEGER NOT NULL,
      used_bytes INTEGER NOT NULL,
      top_consumer_name TEXT,
      top_consumer_kind TEXT,
      top_consumer_rss_bytes INTEGER,
      report_json TEXT NOT NULL,
      suggestions_json TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_snapshots_created_at
      ON memory_snapshots(created_at DESC)
    """,
)

_MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (1, _MIGRATION_1_DISK),
    (2, _MIGRATION_2_MEMORY),
]

# The current schema version is, by construction, the highest migration target.
_SCHEMA_VERSION = _MIGRATIONS[-1][0]


def _current_schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest recorded migration version, treating a fresh or
    un-stamped database (no schema_migrations table, or no rows) as version 0."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


class SQLiteStorage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def write_disk_snapshot(self, report: Report) -> StoredSnapshot:
        name = _snapshot_name(report)
        report_json = report.to_json()
        per_provider = _per_provider(report)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO disk_snapshots (
                  name, kind, scanned_at, hostname, platform, note, total_bytes,
                  duration_ms, entry_count, per_provider_json, report_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    report.kind.value,
                    report.scanned_at.isoformat(),
                    report.hostname,
                    report.platform,
                    report.note,
                    report.total_bytes(),
                    report.duration_ms,
                    len(report.entries) if report.kind.value == "manual" else None,
                    json.dumps(per_provider) if per_provider is not None else None,
                    report_json,
                ),
            )
        return StoredSnapshot(name=name, path=_snapshot_path(self.path, name))

    def list_disk_snapshots(
        self,
        *,
        limit: int | None = None,
        kind: SnapshotKind | None = None,
    ) -> list[StoredSnapshotMeta]:
        params: list[object] = []
        where = ""
        if kind is not None:
            where = "WHERE kind = ?"
            params.append(kind.value)
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT name, kind, scanned_at, hostname, platform, note, total_bytes,
                       duration_ms, entry_count, per_provider_json
                FROM disk_snapshots
                {where}
                ORDER BY scanned_at DESC, name DESC
                {limit_clause}
                """,
                params,
            ).fetchall()
        return [
            StoredSnapshotMeta(
                name=str(row["name"]),
                path=_snapshot_path(self.path, str(row["name"])),
                scanned_at=str(row["scanned_at"]),
                hostname=str(row["hostname"]),
                platform=str(row["platform"]),
                note=row["note"],
                total_bytes=int(row["total_bytes"]),
                kind=str(row["kind"]),
                duration_ms=row["duration_ms"],
                entry_count=row["entry_count"],
                per_provider=json.loads(row["per_provider_json"])
                if row["per_provider_json"]
                else None,
            )
            for row in rows
        ]

    def load_disk_snapshot(self, name: str) -> Report:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM disk_snapshots WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(name)
        return Report.from_json(str(row["report_json"]))

    def prune_auto_disk_snapshots(self, *, keep: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM disk_snapshots
                WHERE kind = ?
                ORDER BY scanned_at DESC, name DESC
                """,
                (SnapshotKind.AUTO.value,),
            ).fetchall()
            victims = [str(row["name"]) for row in rows[keep:]]
            if victims:
                conn.executemany(
                    "DELETE FROM disk_snapshots WHERE name = ?",
                    [(name,) for name in victims],
                )
        return victims

    def write_disk_dashboard_summary(self, report: Report) -> None:
        summary = build_disk_dashboard_summary(report)
        payload_json = json.dumps(disk_dashboard_summary_to_dict(summary), sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dashboard_cache (key, updated_at, payload_json)
                VALUES (?, ?, ?)
                """,
                ("disk-summary", summary.scanned_at, payload_json),
            )

    def load_disk_dashboard_summary(self) -> DiskDashboardSummary | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM dashboard_cache WHERE key = ?",
                ("disk-summary",),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return disk_dashboard_summary_from_dict(cast(dict[str, object], payload))
        except (KeyError, TypeError, ValueError):
            return None

    def append_audit_event(self, event: Mapping[str, object]) -> None:
        payload = dict(event)
        payload.setdefault("at", datetime.now(UTC).isoformat())
        payload.setdefault("schema_version", history_log.AUDIT_SCHEMA_VERSION)
        event_type = str(payload.get("type", "event"))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_events (at, type, payload_json) VALUES (?, ?, ?)",
                (str(payload["at"]), event_type, json.dumps(payload, sort_keys=True)),
            )

    def read_audit_events(self, *, limit: int | None = None) -> list[dict[str, object]]:
        params: list[object] = []
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload_json
                FROM audit_events
                ORDER BY at DESC, id DESC
                {limit_clause}
                """,
                params,
            ).fetchall()
        out: list[dict[str, object]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                out.append(payload)
        return out

    def import_filesystem(self, source: FilesystemStorage) -> tuple[int, int]:
        snapshots = 0
        events = 0
        existing_events = {
            json.dumps(event, sort_keys=True) for event in self.read_audit_events(limit=None)
        }
        for meta in source.list_disk_snapshots(kind=None):
            try:
                report = source.load_disk_snapshot(meta.name)
            except FileNotFoundError:
                continue
            before = len(self.list_disk_snapshots(limit=None, kind=None))
            self.write_disk_snapshot(report)
            after = len(self.list_disk_snapshots(limit=None, kind=None))
            snapshots += 1 if after > before else 0

        for event in reversed(source.read_audit_events(limit=None)):
            key = json.dumps(event, sort_keys=True)
            if key in existing_events:
                continue
            self.append_audit_event(event)
            existing_events.add(key)
            events += 1
        return snapshots, events

    def write_memory_observation(
        self,
        report: MemoryReport,
        suggestions: list[MemorySuggestion],
    ) -> str:
        observation_id = _memory_observation_id(report.scanned_at)
        meta = _memory_observation_meta(
            StoredMemoryObservation(
                id=observation_id,
                report=report,
                suggestions=suggestions,
            )
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_observations (
                  id, scanned_at, pressure, total_bytes, available_bytes, used_bytes,
                  swap_used_bytes, compressed_bytes, top_consumer_name, top_consumer_kind,
                  top_consumer_rss_bytes, suggestion_count, report_json, suggestions_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    meta.scanned_at,
                    meta.pressure,
                    meta.total_bytes,
                    meta.available_bytes,
                    meta.used_bytes,
                    meta.swap_used_bytes,
                    meta.compressed_bytes,
                    meta.top_consumer_name,
                    meta.top_consumer_kind,
                    meta.top_consumer_rss_bytes,
                    meta.suggestion_count,
                    json.dumps(memory_serde.report_to_dict(report), sort_keys=True),
                    json.dumps(memory_serde.suggestions_to_list(suggestions), sort_keys=True),
                ),
            )
        return observation_id

    def list_memory_observations(
        self,
        *,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[MemoryObservationMeta]:
        params: list[object] = []
        where = ""
        if since is not None:
            where = "WHERE scanned_at >= ?"
            params.append(since.isoformat())
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, scanned_at, pressure, total_bytes, available_bytes, used_bytes,
                       swap_used_bytes, compressed_bytes, top_consumer_name, top_consumer_kind,
                       top_consumer_rss_bytes, suggestion_count
                FROM memory_observations
                {where}
                ORDER BY scanned_at DESC, id DESC
                {limit_clause}
                """,
                params,
            ).fetchall()
        return [_memory_observation_meta_from_row(row) for row in rows]

    def latest_memory_observation(self) -> MemoryObservationMeta | None:
        # Indexed ORDER BY scanned_at DESC LIMIT 1 — no full scan.
        rows = self.list_memory_observations(limit=1)
        return rows[0] if rows else None

    def load_memory_observation(self, observation_id: str) -> StoredMemoryObservation:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, report_json, suggestions_json
                FROM memory_observations
                WHERE id = ?
                """,
                (observation_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(observation_id)
        return StoredMemoryObservation(
            id=str(row["id"]),
            report=memory_serde.report_from_dict(json.loads(row["report_json"])),
            suggestions=memory_serde.suggestions_from_list(json.loads(row["suggestions_json"])),
        )

    def prune_memory_observations(self, *, keep: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM memory_observations
                ORDER BY scanned_at DESC, id DESC
                """
            ).fetchall()
            victims = [str(row["id"]) for row in rows[keep:]]
            if victims:
                conn.executemany(
                    "DELETE FROM memory_observations WHERE id = ?",
                    [(victim,) for victim in victims],
                )
        return victims

    def create_memory_snapshot(
        self,
        report: MemoryReport,
        suggestions: list[MemorySuggestion],
        *,
        note: str | None = None,
    ) -> MemorySnapshotMeta:
        created_at = datetime.now(UTC)
        name = _memory_snapshot_name(created_at)
        stored = StoredMemorySnapshot(
            name=name,
            created_at=created_at.isoformat(),
            note=note,
            report=report,
            suggestions=suggestions,
        )
        meta = _memory_snapshot_meta(stored)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_snapshots (
                  name, created_at, scanned_at, note, pressure, total_bytes,
                  available_bytes, used_bytes, top_consumer_name, top_consumer_kind,
                  top_consumer_rss_bytes, report_json, suggestions_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta.name,
                    meta.created_at,
                    meta.scanned_at,
                    meta.note,
                    meta.pressure,
                    meta.total_bytes,
                    meta.available_bytes,
                    meta.used_bytes,
                    meta.top_consumer_name,
                    meta.top_consumer_kind,
                    meta.top_consumer_rss_bytes,
                    json.dumps(memory_serde.report_to_dict(report), sort_keys=True),
                    json.dumps(memory_serde.suggestions_to_list(suggestions), sort_keys=True),
                ),
            )
        return meta

    def list_memory_snapshots(self, *, limit: int | None = None) -> list[MemorySnapshotMeta]:
        params: list[object] = []
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT name, created_at, scanned_at, note, pressure, total_bytes,
                       available_bytes, used_bytes, top_consumer_name, top_consumer_kind,
                       top_consumer_rss_bytes
                FROM memory_snapshots
                ORDER BY created_at DESC, name DESC
                {limit_clause}
                """,
                params,
            ).fetchall()
        return [_memory_snapshot_meta_from_row(row) for row in rows]

    def load_memory_snapshot(self, name: str) -> StoredMemorySnapshot:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT name, created_at, note, report_json, suggestions_json
                FROM memory_snapshots
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(name)
        return StoredMemorySnapshot(
            name=str(row["name"]),
            created_at=str(row["created_at"]),
            note=cast(str | None, row["note"]),
            report=memory_serde.report_from_dict(json.loads(row["report_json"])),
            suggestions=memory_serde.suggestions_from_list(json.loads(row["suggestions_json"])),
        )

    def _ensure_schema(self) -> None:
        """Bring the database up to _SCHEMA_VERSION by applying, in order, every
        migration whose target version exceeds the recorded version.

        States handled:
          * brand-new DB (version 0)  -> migrations 1..N run to build the schema;
          * DB already at latest       -> the loop applies nothing (no-op);
          * DB at an older version     -> only the gap is applied.

        Each migration runs in its own explicit transaction and stamps its
        version on success, so an interrupted upgrade leaves the DB at a clean
        intermediate version and re-running simply resumes. Because every
        statement is IF NOT EXISTS, applying a migration to a DB that already
        holds those objects is harmless and preserves existing rows.
        """
        conn = self._connect()
        # Take manual control of transactions so DDL is grouped atomically with
        # its version stamp (SQLite supports transactional DDL); the default
        # driver isolation would auto-commit each statement on its own.
        conn.isolation_level = None
        try:
            conn.executescript(_SCHEMA_MIGRATIONS_DDL)
            current = _current_schema_version(conn)
            for version, statements in _MIGRATIONS:
                if version <= current:
                    continue
                conn.execute("BEGIN")
                try:
                    for statement in statements:
                        conn.execute(statement)
                    conn.execute(
                        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                        "VALUES (?, ?)",
                        (version, datetime.now(UTC).isoformat()),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        # The CLI and web server can write this DB concurrently. WAL lets a
        # reader proceed during a write, and busy_timeout makes a contending
        # writer wait instead of failing immediately with "database is locked".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def _snapshot_name(report: Report) -> str:
    # Microsecond precision so two same-second scans don't collide on the
    # primary key and clobber each other via INSERT OR REPLACE. Matches the
    # filesystem backend's naming so import_filesystem dedupes correctly.
    stamp = report.scanned_at.strftime("%Y-%m-%dT%H-%M-%S-%f")
    return f"{stamp}--{report.kind.value}.json"


def _snapshot_path(db_path: Path, name: str) -> str:
    return f"sqlite://{db_path}#{name}"


def _per_provider(report: Report) -> list[dict[str, object]] | None:
    if not report.per_provider:
        return None
    return [
        {
            "name": pt.name,
            "bytes": pt.bytes,
            "entries": pt.entries,
            "duration_ms": pt.duration_ms,
        }
        for pt in report.per_provider
    ]


def _memory_observation_id(scanned_at: datetime) -> str:
    stamp = scanned_at.strftime("%Y-%m-%dT%H-%M-%S-%f")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _memory_snapshot_name(created_at: datetime) -> str:
    return created_at.strftime("%Y-%m-%dT%H-%M-%S-%f")


def _memory_observation_meta_from_row(row: sqlite3.Row) -> MemoryObservationMeta:
    return MemoryObservationMeta(
        id=str(row["id"]),
        scanned_at=str(row["scanned_at"]),
        pressure=str(row["pressure"]),
        total_bytes=int(row["total_bytes"]),
        available_bytes=int(row["available_bytes"]),
        used_bytes=int(row["used_bytes"]),
        swap_used_bytes=cast(int | None, row["swap_used_bytes"]),
        compressed_bytes=cast(int | None, row["compressed_bytes"]),
        top_consumer_name=cast(str | None, row["top_consumer_name"]),
        top_consumer_kind=cast(str | None, row["top_consumer_kind"]),
        top_consumer_rss_bytes=cast(int | None, row["top_consumer_rss_bytes"]),
        suggestion_count=int(row["suggestion_count"]),
    )


def _memory_snapshot_meta_from_row(row: sqlite3.Row) -> MemorySnapshotMeta:
    return MemorySnapshotMeta(
        name=str(row["name"]),
        created_at=str(row["created_at"]),
        scanned_at=str(row["scanned_at"]),
        note=cast(str | None, row["note"]),
        pressure=str(row["pressure"]),
        total_bytes=int(row["total_bytes"]),
        available_bytes=int(row["available_bytes"]),
        used_bytes=int(row["used_bytes"]),
        top_consumer_name=cast(str | None, row["top_consumer_name"]),
        top_consumer_kind=cast(str | None, row["top_consumer_kind"]),
        top_consumer_rss_bytes=cast(int | None, row["top_consumer_rss_bytes"]),
    )
