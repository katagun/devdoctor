"""Append-only JSONL audit log for cleanup jobs.

Records what was cleaned, when, and with what outcome so the Web UI can show
a history timeline. One line per event; O(1) append, O(n) read.

Atomicity note
~~~~~~~~~~~~~~
``append_event`` relies on POSIX append-mode writes being atomic for payloads
up to ``PIPE_BUF`` (4 KB on macOS/Linux). Every event we emit is a flat JSON
object well under that ceiling, so concurrent appends from separate processes
interleave at line boundaries rather than corrupting each other mid-line.
If event payloads ever grow beyond a few hundred bytes per field, revisit.

Rotation
~~~~~~~~
When ``audit.jsonl`` crosses ``MAX_LOG_BYTES``, it is renamed to
``audit.1.jsonl`` (and any existing ``audit.1.jsonl`` cascades down through
``audit.{N}.jsonl`` up to ``KEEP_ROTATIONS``, after which the oldest is
dropped). ``read_events`` reads back across all rotations newest-first so
the history page sees a continuous stream.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from devdoctor._storage import default_data_dir

# Schema version stamped into every event. Additive changes (new keys) don't
# need a bump; renames/removals do. Readers should treat unknown versions as
# "read what you can" rather than erroring.
AUDIT_SCHEMA_VERSION = 1

# Rotate at 5 MB. Keeps the hot file small enough to read quickly while giving
# a heavy user ~weeks of history per rotation.
MAX_LOG_BYTES = 5 * 1024 * 1024

# Number of rotated files kept alongside the active log (audit.1 … audit.N).
# Total worst-case disk footprint: (KEEP_ROTATIONS + 1) * MAX_LOG_BYTES.
KEEP_ROTATIONS = 3


def default_audit_dir() -> Path:
    """Directory that holds the audit log — colocated with snapshots."""
    return default_data_dir()


def default_audit_path() -> Path:
    return default_audit_dir() / "audit.jsonl"


def _rotation_path(base: Path, n: int) -> Path:
    """Return ``base``'s n-th rotated filename. ``n=0`` is the live file."""
    if n == 0:
        return base
    return base.with_name(base.stem + f".{n}" + base.suffix)


def _rotate(base: Path) -> None:
    """Shift live → .1 → .2 → … → KEEP_ROTATIONS, dropping the oldest.

    Uses ``os.replace`` throughout so each rename is atomic and overwrites
    the destination. The loop runs from oldest to newest so each step's
    destination is free by the time we rename into it.
    """
    for n in range(KEEP_ROTATIONS - 1, -1, -1):
        src = _rotation_path(base, n)
        dst = _rotation_path(base, n + 1)
        if src.exists():
            os.replace(src, dst)


def _maybe_rotate(base: Path) -> None:
    try:
        size = base.stat().st_size
    except OSError:
        return
    if size >= MAX_LOG_BYTES:
        _rotate(base)


def append_event(event: dict[str, Any], path: Path | None = None) -> None:
    """Append a single JSON event as one line. Creates the file if needed.

    The event is given an ``at`` ISO timestamp and a ``schema_version`` if
    the caller hasn't supplied one, so every line is self-locating in time
    and evolvable.
    """
    target = path or default_audit_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    _maybe_rotate(target)
    payload = dict(event)
    payload.setdefault("at", datetime.now(UTC).isoformat())
    payload.setdefault("schema_version", AUDIT_SCHEMA_VERSION)
    line = json.dumps(payload, sort_keys=True)
    # Open in append mode so concurrent writes don't clobber each other
    # (see module docstring on PIPE_BUF atomicity).
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_events(path: Path | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Read events newest-first across the live log and any rotations.

    Stops reading further rotated files once ``limit`` has been satisfied.
    Malformed lines are skipped so one corrupt record never poisons the
    rest of the stream.
    """
    base = path or default_audit_path()
    out: list[dict[str, Any]] = []
    for n in range(KEEP_ROTATIONS + 1):
        f = _rotation_path(base, n)
        if not f.is_file():
            continue
        file_events: list[dict[str, Any]] = []
        with f.open("r", encoding="utf-8") as fp:
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if isinstance(ev, dict):
                        file_events.append(ev)
                except json.JSONDecodeError:
                    continue
        file_events.reverse()  # newest-first within this file
        out.extend(file_events)
        if limit is not None and len(out) >= limit:
            return out[:limit]
    return out if limit is None else out[:limit]
