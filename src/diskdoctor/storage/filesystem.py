from __future__ import annotations

import contextlib
import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from diskdoctor import history, history_log
from diskdoctor._storage import default_data_dir
from diskdoctor.dashboard import (
    build_disk_dashboard_summary,
    disk_dashboard_summary_from_dict,
    disk_dashboard_summary_to_dict,
)
from diskdoctor.memory import serde as memory_serde
from diskdoctor.memory.types import MemoryConsumer, MemoryReport, MemorySuggestion
from diskdoctor.storage.base import (
    DiskDashboardSummary,
    MemoryObservationMeta,
    MemorySnapshotMeta,
    StoredMemoryObservation,
    StoredMemorySnapshot,
    StoredSnapshot,
    StoredSnapshotMeta,
)
from diskdoctor.types import Report, SnapshotKind

# Extra observations tolerated above `keep` before a prune rewrites the file.
# Batches the O(file) rewrite across this many appends instead of every write.
_PRUNE_SLACK = 256

# Enough to hold the last JSONL record even for a busy machine (dozens of
# consumers). If a single record ever exceeds this, the tail read simply
# reports "no latest" and the caller records again — a safe over-count.
_TAIL_READ_BYTES = 256 * 1024


def _count_lines(path: Path) -> int:
    """Count newlines in a file cheaply (binary, no decode/parse)."""
    total = 0
    try:
        with path.open("rb") as f:
            while True:
                block = f.read(1 << 20)
                if not block:
                    break
                total += block.count(b"\n")
    except OSError:
        return 0
    return total


def _read_last_json_line(path: Path) -> dict[str, Any] | None:
    """Parse the last non-empty JSON object in an append-only JSONL file.

    Reads only a bounded tail rather than the whole file. Returns None if the
    file is missing/empty or the final record can't be parsed.
    """
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _TAIL_READ_BYTES))
            data = f.read()
    except OSError:
        return None
    lines = [ln for ln in data.split(b"\n") if ln.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return cast(dict[str, Any], payload) if isinstance(payload, dict) else None


def _safe_component(name: str) -> str:
    """Reject any snapshot name that isn't a single, literal path component.

    Snapshot names arrive from HTTP query params (`/api/diff`,
    `/api/memory/snapshots/diff`) and get joined onto the storage directory.
    A name containing `/`, `..`, or an absolute path would escape that
    directory (`Path(dir) / "/etc/x" == Path("/etc/x")`), turning the loader
    into an arbitrary-file read. Callers treat the raised error as "not
    found", so bad names are indistinguishable from missing snapshots.
    """
    if name != Path(name).name or name in ("", ".", ".."):
        raise FileNotFoundError(name)
    return name


class FilesystemStorage:
    def __init__(self, *, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir

    def snapshot_dir(self) -> Path:
        return self.data_dir() / "snapshots"

    def audit_path(self) -> Path:
        return self.data_dir() / "audit.jsonl"

    def data_dir(self) -> Path:
        return self._data_dir or default_data_dir()

    def memory_observations_path(self) -> Path:
        return self.data_dir() / "memory" / "observations.jsonl"

    def memory_snapshots_dir(self) -> Path:
        return self.data_dir() / "memory" / "snapshots"

    def disk_dashboard_summary_path(self) -> Path:
        return self.data_dir() / "dashboard" / "disk-summary.json"

    def write_disk_snapshot(self, report: Report) -> StoredSnapshot:
        target = history.write_snapshot(report, self.snapshot_dir())
        return StoredSnapshot(name=target.name, path=str(target))

    def list_disk_snapshots(
        self,
        *,
        limit: int | None = None,
        kind: SnapshotKind | None = None,
    ) -> list[StoredSnapshotMeta]:
        out: list[StoredSnapshotMeta] = []
        directory = self.snapshot_dir()
        if not directory.exists():
            return out
        for path in sorted(directory.glob("*.json"), reverse=True):
            try:
                report = Report.from_json(path.read_text())
            except Exception:
                continue
            if kind is not None and report.kind != kind:
                continue
            out.append(_snapshot_meta(path.name, str(path), report))
            if limit is not None and len(out) >= limit:
                break
        return out

    def load_disk_snapshot(self, name: str) -> Report:
        path = self.snapshot_dir() / _safe_component(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        return Report.from_json(path.read_text())

    def prune_auto_disk_snapshots(self, *, keep: int) -> list[str]:
        return [p.name for p in history.prune_auto_snapshots(self.snapshot_dir(), keep=keep)]

    def write_disk_dashboard_summary(self, report: Report) -> None:
        summary = build_disk_dashboard_summary(report)
        target = self.disk_dashboard_summary_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        try:
            tmp.write_text(
                json.dumps(disk_dashboard_summary_to_dict(summary), indent=2, sort_keys=True) + "\n"
            )
            os.replace(tmp, target)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    def load_disk_dashboard_summary(self) -> DiskDashboardSummary | None:
        target = self.disk_dashboard_summary_path()
        if not target.is_file():
            return None
        try:
            payload = json.loads(target.read_text())
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return disk_dashboard_summary_from_dict(cast(dict[str, object], payload))
        except (KeyError, TypeError, ValueError):
            return None

    def append_audit_event(self, event: Mapping[str, object]) -> None:
        history_log.append_event(dict(event), path=self.audit_path())

    def read_audit_events(self, *, limit: int | None = None) -> list[dict[str, object]]:
        return history_log.read_events(path=self.audit_path(), limit=limit)

    def write_memory_observation(
        self,
        report: MemoryReport,
        suggestions: list[MemorySuggestion],
    ) -> str:
        observation_id = _memory_observation_id(report.scanned_at)
        payload = {
            "id": observation_id,
            "report": memory_serde.report_to_dict(report),
            "suggestions": memory_serde.suggestions_to_list(suggestions),
        }
        target = self.memory_observations_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")
        return observation_id

    def list_memory_observations(
        self,
        *,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[MemoryObservationMeta]:
        rows = [
            _memory_observation_meta(stored)
            for stored in self._read_memory_observations()
            if since is None or stored.report.scanned_at >= since
        ]
        rows.sort(key=lambda row: row.scanned_at, reverse=True)
        return rows[:limit] if limit is not None else rows

    def load_memory_observation(self, observation_id: str) -> StoredMemoryObservation:
        for stored in self._read_memory_observations():
            if stored.id == observation_id:
                return stored
        raise FileNotFoundError(observation_id)

    def latest_memory_observation(self) -> MemoryObservationMeta | None:
        """Return the newest observation's metadata without parsing the file.

        Observations are appended chronologically, so the last line is the
        newest. Reading just that line keeps the dashboard's per-poll
        "should I record?" check O(1) instead of deserializing every stored
        observation on every poll.
        """
        payload = _read_last_json_line(self.memory_observations_path())
        if payload is None:
            return None
        return _memory_observation_meta(_stored_observation_from_payload(payload))

    def prune_memory_observations(self, *, keep: int) -> list[str]:
        # Cheap gate: only pay the full read + rewrite once we're meaningfully
        # over the cap. A per-write rewrite of the whole JSONL (the dashboard
        # writes on every recorded poll) is the dominant cost otherwise; the
        # slack amortizes it across many appends.
        target = self.memory_observations_path()
        if not target.is_file() or _count_lines(target) <= keep + _PRUNE_SLACK:
            return []
        observations = sorted(
            self._read_memory_observations(),
            key=lambda row: row.report.scanned_at,
            reverse=True,
        )
        victims = observations[keep:]
        if not victims:
            return []
        tmp = target.with_name(target.name + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                for stored in observations[:keep]:
                    line = json.dumps(_stored_observation_to_payload(stored), sort_keys=True)
                    f.write(line + "\n")
            os.replace(tmp, target)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
        return [v.id for v in victims]

    def create_memory_snapshot(
        self,
        report: MemoryReport,
        suggestions: list[MemorySuggestion],
        *,
        note: str | None = None,
    ) -> MemorySnapshotMeta:
        created_at = datetime.now(UTC)
        name = _memory_snapshot_name(created_at)
        payload = {
            "name": name,
            "created_at": created_at.isoformat(),
            "note": note,
            "report": memory_serde.report_to_dict(report),
            "suggestions": memory_serde.suggestions_to_list(suggestions),
        }
        target = self.memory_snapshots_dir() / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            os.replace(tmp, target)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
        return _memory_snapshot_meta(_stored_snapshot_from_payload(payload))

    def list_memory_snapshots(self, *, limit: int | None = None) -> list[MemorySnapshotMeta]:
        snapshots = [_memory_snapshot_meta(s) for s in self._read_memory_snapshots()]
        snapshots.sort(key=lambda row: row.created_at, reverse=True)
        return snapshots[:limit] if limit is not None else snapshots

    def load_memory_snapshot(self, name: str) -> StoredMemorySnapshot:
        path = self.memory_snapshots_dir() / f"{_safe_component(name)}.json"
        if not path.is_file():
            raise FileNotFoundError(name)
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise FileNotFoundError(name) from exc
        return _stored_snapshot_from_payload(cast(dict[str, Any], payload))

    def _read_memory_observations(self) -> list[StoredMemoryObservation]:
        target = self.memory_observations_path()
        if not target.is_file():
            return []
        out: list[StoredMemoryObservation] = []
        with target.open("r", encoding="utf-8") as f:
            for raw in f:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    out.append(_stored_observation_from_payload(cast(dict[str, Any], payload)))
        return out

    def _read_memory_snapshots(self) -> list[StoredMemorySnapshot]:
        directory = self.memory_snapshots_dir()
        if not directory.exists():
            return []
        out: list[StoredMemorySnapshot] = []
        for path in directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                out.append(_stored_snapshot_from_payload(cast(dict[str, Any], payload)))
        return out


def _snapshot_meta(name: str, path: str, report: Report) -> StoredSnapshotMeta:
    return StoredSnapshotMeta(
        name=name,
        path=path,
        scanned_at=report.scanned_at.isoformat(),
        hostname=report.hostname,
        platform=report.platform,
        note=report.note,
        total_bytes=report.total_bytes(),
        kind=report.kind.value,
        duration_ms=report.duration_ms,
        entry_count=len(report.entries) if report.kind.value == "manual" else None,
        per_provider=[
            {
                "name": pt.name,
                "bytes": pt.bytes,
                "entries": pt.entries,
                "duration_ms": pt.duration_ms,
            }
            for pt in report.per_provider
        ]
        if report.per_provider
        else None,
    )


def _memory_observation_id(scanned_at: datetime) -> str:
    stamp = scanned_at.strftime("%Y-%m-%dT%H-%M-%S-%f")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _memory_snapshot_name(created_at: datetime) -> str:
    return created_at.strftime("%Y-%m-%dT%H-%M-%S-%f")


def _stored_observation_to_payload(stored: StoredMemoryObservation) -> dict[str, object]:
    return {
        "id": stored.id,
        "report": memory_serde.report_to_dict(stored.report),
        "suggestions": memory_serde.suggestions_to_list(stored.suggestions),
    }


def _stored_observation_from_payload(payload: dict[str, Any]) -> StoredMemoryObservation:
    return StoredMemoryObservation(
        id=str(payload["id"]),
        report=memory_serde.report_from_dict(cast(dict[str, Any], payload["report"])),
        suggestions=memory_serde.suggestions_from_list(cast(list[object], payload["suggestions"])),
    )


def _stored_snapshot_from_payload(payload: dict[str, Any]) -> StoredMemorySnapshot:
    return StoredMemorySnapshot(
        name=str(payload["name"]),
        created_at=str(payload["created_at"]),
        note=None if payload.get("note") is None else str(payload["note"]),
        report=memory_serde.report_from_dict(cast(dict[str, Any], payload["report"])),
        suggestions=memory_serde.suggestions_from_list(
            cast(list[object], payload.get("suggestions", []))
        ),
    )


def _memory_observation_meta(stored: StoredMemoryObservation) -> MemoryObservationMeta:
    top = _top_consumer(stored.report)
    return MemoryObservationMeta(
        id=stored.id,
        scanned_at=stored.report.scanned_at.isoformat(),
        pressure=stored.report.system.pressure,
        total_bytes=stored.report.system.total_bytes,
        available_bytes=stored.report.system.available_bytes,
        used_bytes=stored.report.system.used_bytes,
        swap_used_bytes=stored.report.system.swap_used_bytes,
        compressed_bytes=stored.report.system.compressed_bytes,
        top_consumer_name=top.name if top else None,
        top_consumer_kind=top.kind if top else None,
        top_consumer_rss_bytes=top.rss_bytes if top else None,
        suggestion_count=len(stored.suggestions),
    )


def _memory_snapshot_meta(stored: StoredMemorySnapshot) -> MemorySnapshotMeta:
    top = _top_consumer(stored.report)
    return MemorySnapshotMeta(
        name=stored.name,
        created_at=stored.created_at,
        scanned_at=stored.report.scanned_at.isoformat(),
        note=stored.note,
        pressure=stored.report.system.pressure,
        total_bytes=stored.report.system.total_bytes,
        available_bytes=stored.report.system.available_bytes,
        used_bytes=stored.report.system.used_bytes,
        top_consumer_name=top.name if top else None,
        top_consumer_kind=top.kind if top else None,
        top_consumer_rss_bytes=top.rss_bytes if top else None,
    )


def _top_consumer(report: MemoryReport) -> MemoryConsumer | None:
    if not report.consumers:
        return None
    return max(report.consumers, key=lambda c: c.rss_bytes)
