"""Shared on-disk layout helpers.

One place that knows where devdoctor persists state so ``history`` and
``history_log`` stay in sync. Both the snapshot JSON files and the audit
log live directly inside ``default_data_dir()``.
"""

from __future__ import annotations

from os import environ
from pathlib import Path


def default_data_dir() -> Path:
    """Top-level directory for all devdoctor on-disk state.

    Resolves to ``$XDG_DATA_HOME/devdoctor`` when XDG_DATA_HOME is set,
    otherwise ``~/.local/share/devdoctor`` — per the XDG Base Directory
    Specification. Falls back to the pre-rename ``diskdoctor`` directory
    when it exists and no ``devdoctor`` directory has been created yet, so
    state written before the rename keeps being used.
    """
    base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    new = Path(base) / "devdoctor"
    legacy = Path(base) / "diskdoctor"
    if not new.exists() and legacy.exists():
        return legacy
    return new
