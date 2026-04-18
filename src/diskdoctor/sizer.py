from __future__ import annotations

import os
from pathlib import Path


def size_path(root: Path) -> tuple[int, list[Path]]:
    """Compute byte size of `root` recursively.

    Symlink-safe (does not follow). Stays on the root's device. Records any
    paths that errored during walk in the returned `skipped` list rather than
    raising.
    """
    skipped: list[Path] = []

    try:
        root_stat = root.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        skipped.append(root)
        return 0, skipped

    root_dev = root_stat.st_dev
    total = 0

    def on_error(err: OSError) -> None:
        filename = getattr(err, "filename", None)
        skipped.append(Path(filename) if filename else root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=on_error):
        dp = Path(dirpath)

        # Cross-device guard: prune subdirs that live on a different device.
        pruned: list[str] = []
        for d in list(dirnames):
            sub = dp / d
            try:
                if sub.lstat().st_dev != root_dev:
                    pruned.append(d)
            except (FileNotFoundError, PermissionError, OSError):
                skipped.append(sub)
                pruned.append(d)
        for d in pruned:
            dirnames.remove(d)

        for name in filenames:
            p = dp / name
            try:
                total += p.lstat().st_size
            except (FileNotFoundError, PermissionError, OSError):
                skipped.append(p)

    return total, skipped
