from __future__ import annotations

import grp
import os
import pwd
import stat as stat_mod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from devdoctor.types import HardlinkRecord


@dataclass(frozen=True)
class StatFields:
    """Owner/group/permission metadata for a single filesystem path.

    Names are resolved via pwd/grp with a small LRU cache so a full scan only
    pays a handful of syscalls even across hundreds of entries. `perms` is the
    `ls -l`-style string from stat.filemode (includes the file-type char).
    """

    uid: int
    gid: int
    mode: int
    owner: str
    group: str
    perms: str


@lru_cache(maxsize=256)
def _owner_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


@lru_cache(maxsize=256)
def _group_name(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def stat_fields(path: Path) -> StatFields | None:
    """Return owner/group/perms for `path`, or None on missing / permission
    errors. Uses lstat so symlinks report their own metadata, not the
    target's — matches how size_path handles symlinks.
    """
    try:
        st = path.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    return StatFields(
        uid=st.st_uid,
        gid=st.st_gid,
        mode=st.st_mode,
        owner=_owner_name(st.st_uid),
        group=_group_name(st.st_gid),
        perms=stat_mod.filemode(st.st_mode),
    )


@dataclass(frozen=True)
class SizeResult:
    allocated_bytes: int
    skipped_paths: tuple[Path, ...]
    hardlinks: tuple[HardlinkRecord, ...]


def size_path(root: Path) -> tuple[int, list[Path]]:
    result = size_path_detailed(root)
    return result.allocated_bytes, list(result.skipped_paths)


def size_path_detailed(root: Path) -> SizeResult:
    """Compute byte size of `root` recursively.

    Symlink-safe (does not follow), stays on the root's device, and dedupes
    hard-linked files by (dev, ino) so a single tree that links
    the same inode from multiple places counts its bytes exactly once.
    Records any paths that errored during walk in the returned `skipped`
    list rather than raising.

    The detailed result carries hard-link identities and observed paths so the
    scan layer can deterministically reconcile allocations shared by separate
    entries and providers after concurrent discovery finishes.
    """
    skipped: list[Path] = []

    try:
        root_stat = root.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        skipped.append(root)
        return SizeResult(0, tuple(skipped), ())

    root_dev = root_stat.st_dev
    total = 0
    seen_inodes: set[tuple[int, int]] = set()
    hardlinks: dict[tuple[int, int], tuple[int, int, list[str]]] = {}

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
            blocks = getattr(st, "st_blocks", 0) * 512
            allocated = min(st.st_size, blocks) if blocks else st.st_size
            # Hard-link dedup: skip bytes we've already counted in
            # this walk. st_nlink > 1 signals the file has other names, but
            # the check is unconditional since the cost is just a set lookup.
            key = (st.st_dev, st.st_ino)
            if st.st_nlink > 1:
                current = hardlinks.get(key)
                if current is None:
                    hardlinks[key] = (allocated, st.st_nlink, [str(p)])
                else:
                    current[2].append(str(p))
            if key in seen_inodes:
                continue
            seen_inodes.add(key)
            # Actual on-disk usage via st_blocks handles sparse files correctly
            # (e.g. Docker.raw reports 80 GB apparent but uses only megabytes).
            # For non-sparse files st_blocks*512 rounds up to a block boundary,
            # so we cap at st_size to preserve per-byte accuracy for normal files.
            total += allocated

    records = tuple(
        HardlinkRecord(
            device=device,
            inode=inode,
            allocated_bytes=allocated,
            link_count=link_count,
            paths=tuple(sorted(set(paths))),
        )
        for (device, inode), (allocated, link_count, paths) in sorted(hardlinks.items())
    )
    return SizeResult(total, tuple(skipped), records)
