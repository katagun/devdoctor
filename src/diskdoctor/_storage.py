"""Shared on-disk layout helpers.

One place that knows where diskdoctor persists state so ``history`` and
``history_log`` stay in sync. Both the snapshot JSON files and the audit
log live directly inside ``default_data_dir()``.
"""

from __future__ import annotations

from os import environ
from pathlib import Path


def default_data_dir() -> Path:
    """Top-level directory for all diskdoctor on-disk state.

    Resolves to ``$XDG_DATA_HOME/diskdoctor`` when XDG_DATA_HOME is set,
    otherwise ``~/.local/share/diskdoctor`` — per the XDG Base Directory
    Specification.
    """
    base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "diskdoctor"
