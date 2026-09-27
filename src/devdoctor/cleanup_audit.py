"""The audit record of one cleanup run, shared by the CLI and the web runner (spec §5.1)."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from devdoctor.cleanup import PlannedEntry
from devdoctor.types import CleanResult, Entry, estimated_reclaimable_bytes

AUDIT_TYPE = "cleanup"

# Below this, the difference between two free-space readings is whatever else wrote
# to the disk in between (logs, caches, a browser), so "released less than half"
# means nothing. 100 MB clears that noise by a wide margin.
SNAPSHOT_HINT_MIN_BYTES = 100_000_000


def free_bytes() -> int | None:
    """Free bytes on the volume holding the home directory; None when unavailable.

    Walks up to the nearest existing ancestor first: a non-existent (but
    otherwise valid) $HOME, as tests pin it, or a fresh account, would
    otherwise make ``disk_usage`` raise even though the volume is readable.
    Note this means a missing $HOME mount can silently report the free space
    of whatever volume holds its nearest existing ancestor (e.g. `/`) instead.
    """
    path = Path.home()
    try:
        while not path.exists():
            path = path.parent
        return shutil.disk_usage(path).free
    except OSError:
        return None


def free_space_lagged(free_before: int | None, free_after: int | None, reclaimed: int) -> bool:
    """Whether the disk released under half of what a cleanup deleted.

    The usual cause on macOS is a Time Machine local snapshot holding the deleted
    files' blocks until it is thinned. Both readings must exist, and the cleanup
    must be large enough for the difference to mean anything.
    """
    if free_before is None or free_after is None:
        return False
    if reclaimed < SNAPSHOT_HINT_MIN_BYTES:
        return False
    return free_after - free_before < reclaimed / 2


def estimated_reclaimed_bytes(entries: Sequence[Entry], results: Sequence[CleanResult]) -> int:
    successful = {r.entry_id for r in results if r.status == "ok"}
    return estimated_reclaimable_bytes([e for e in entries if e.id in successful])


def all_bytes_verified(results: Sequence[CleanResult]) -> bool:
    successful = [r for r in results if r.status == "ok"]
    return bool(successful) and all(r.bytes_verified for r in successful)


def build_event(
    results: Sequence[CleanResult],
    outcome: str,
    *,
    source: Literal["cli", "web"],
    plan: Sequence[PlannedEntry],
    entries: Sequence[Entry],
    job_id: str | None = None,
    error: str | None = None,
    free_before: int | None = None,
    free_after: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    by_id = {e.id: e for e in entries}
    estimated = estimated_reclaimed_bytes(entries, results)
    event: dict[str, Any] = {
        "type": AUDIT_TYPE,
        "source": source,
        "job_id": job_id,
        "at": (now or datetime.now(UTC)).isoformat(),
        "outcome": outcome,
        # Compatibility key for audit readers written before explicit estimate semantics.
        "total_freed_bytes": estimated,
        "total_estimated_reclaimed_bytes": estimated,
        "bytes_verified": all_bytes_verified(results),
        "free_before_bytes": free_before,
        "free_after_bytes": free_after,
        "plan": [
            {
                "entry_id": p.entry.id,
                "provider": p.entry.provider,
                "label": p.entry.label,
                "path": None if p.entry.path is None else str(p.entry.path),
                "risk": p.entry.risk.value,
                "estimate_bytes": p.estimate_bytes,
                "actions": list(p.lines),
            }
            for p in plan
        ],
        "results": [
            {
                "entry_id": r.entry_id,
                "status": r.status,
                "freed_bytes": r.freed_bytes,
                "message": r.message,
                "bytes_verified": r.bytes_verified,
                "provider": _field(by_id.get(r.entry_id), "provider"),
                "label": _field(by_id.get(r.entry_id), "label"),
                "path": _path(by_id.get(r.entry_id)),
            }
            for r in results
        ],
    }
    if error is not None:
        event["error"] = error
    return event


def _field(entry: Entry | None, name: str) -> str | None:
    return None if entry is None else str(getattr(entry, name))


def _path(entry: Entry | None) -> str | None:
    return None if entry is None or entry.path is None else str(entry.path)
