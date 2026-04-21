"""Append-only JSONL audit log for cleanup jobs.

Records what was cleaned, when, and with what outcome so the Web UI can show
a history timeline. One line per event; O(1) append, O(n) read.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from os import environ
from pathlib import Path
from typing import Any


def default_audit_dir() -> Path:
    """Directory that holds the audit log — colocated with snapshots."""
    base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "diskdoctor"


def default_audit_path() -> Path:
    return default_audit_dir() / "audit.jsonl"


def append_event(event: dict[str, Any], path: Path | None = None) -> None:
    """Append a single JSON event as one line. Creates the file if needed.

    The event is given an ``at`` ISO timestamp if the caller hasn't supplied
    one so every line is self-locating in time.
    """
    target = path or default_audit_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("at", datetime.now(UTC).isoformat())
    line = json.dumps(payload, sort_keys=True)
    # Open in append mode so concurrent writes don't clobber each other.
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_events(path: Path | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Read events from the log, newest first. Malformed lines are skipped."""
    target = path or default_audit_path()
    if not target.is_file():
        return []
    events: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if isinstance(ev, dict):
                    events.append(ev)
            except json.JSONDecodeError:
                continue
    events.reverse()
    if limit is not None:
        return events[:limit]
    return events
