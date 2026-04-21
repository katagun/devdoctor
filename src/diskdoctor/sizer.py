from __future__ import annotations

import os
from pathlib import Path


def size_path(root: Path) -> tuple[int, list[Path]]:
    """Compute byte size of `root` recursively.

    Symlink-safe (does not follow), stays on the root's device, and dedupes
    hard-linked / reflinked files by (dev, ino) so a single tree that links
    the same inode from multiple places counts its bytes exactly once.
    Records any paths that errored during walk in the returned `skipped`
    list rather than raising.

    Note: the inode dedup is scoped to a single `size_path` invocation.
    Two providers that separately scan trees sharing hard links will still
    each count the shared bytes — fixing that would require a process-wide
    inode tracker threaded through the scan, which we haven't introduced.
    """
    skipped: list[Path] = []

    try:
        root_stat = root.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        skipped.append(root)
        return 0, skipped

    root_dev = root_stat.st_dev
    total = 0
    seen_inodes: set[tuple[int, int]] = set()

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
                st = p.lstat()
            except (FileNotFoundError, PermissionError, OSError):
                skipped.append(p)
                continue
            # Hard-link / reflink dedup: skip bytes we've already counted in
            # this walk. st_nlink > 1 signals the file has other names, but
            # the check is unconditional since the cost is just a set lookup.
            key = (st.st_dev, st.st_ino)
            if key in seen_inodes:
                continue
            seen_inodes.add(key)
            # Actual on-disk usage via st_blocks handles sparse files correctly
            # (e.g. Docker.raw reports 80 GB apparent but uses only megabytes).
            # For non-sparse files st_blocks*512 rounds up to a block boundary,
            # so we cap at st_size to preserve per-byte accuracy for normal files.
            blocks = getattr(st, "st_blocks", 0) * 512
            total += min(st.st_size, blocks) if blocks else st.st_size

    return total, skipped
