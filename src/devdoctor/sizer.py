from __future__ import annotations

import grp
import os
import pwd
import stat as stat_mod
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
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
    # The sum of the files' lengths. It exceeds ``allocated_bytes`` for a sparse
    # file such as a VM disk image, which reserves address space it has not written.
    apparent_bytes: int = 0
    # The most recent modification of the root or anything inside it; None when the
    # root could not be read. A directory's own mtime only moves when its direct
    # children change, so it says nothing about files further down.
    newest_mtime: float | None = None


def size_path(root: Path) -> tuple[int, list[Path]]:
    result = size_path_detailed(root)
    return result.allocated_bytes, list(result.skipped_paths)


# How many trees are walked at once, across the whole process. Providers run on
# their own threads and each used to walk its trees one after another, so a scan
# was as slow as its slowest provider. Walking is ``lstat`` after ``lstat``, which
# releases the GIL, so a few walks overlap well. Past a handful they contend
# inside the filesystem instead: on the reference APFS SSD 4 walks sized the same
# trees 5x faster than 1, and 16 walks were slower than 4 (#92).
MAX_CONCURRENT_WALKS = 4
_WORKERS_ENV = "DEVDOCTOR_SIZER_WORKERS"

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _walk_pool() -> ThreadPoolExecutor:
    """The one pool every walk runs on, which is what makes the bound global."""
    global _pool  # noqa: PLW0603 - a lazily created process-wide singleton
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=_worker_count(), thread_name_prefix="dd-sizer")
        return _pool


def _worker_count() -> int:
    raw = os.environ.get(_WORKERS_ENV, "")
    try:
        return max(1, int(raw)) if raw else MAX_CONCURRENT_WALKS
    except ValueError:
        return MAX_CONCURRENT_WALKS


def size_many(roots: Sequence[Path]) -> list[SizeResult]:
    """Size every root, a few at a time; results keep the order of ``roots``.

    Walks never start other walks, so callers blocking here cannot deadlock the pool.
    """
    pool = _walk_pool()
    futures = [pool.submit(_walk, root) for root in roots]
    return [future.result() for future in futures]


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

    Runs on the shared walk pool, so the number of simultaneous walks is bounded
    whatever the number of calling threads; ``size_many`` sizes several at once.
    """
    return size_many([root])[0]


def _lstat(entry: os.DirEntry[str]) -> os.stat_result:
    """The one stat a walk makes per directory entry; a seam for the tests."""
    return entry.stat(follow_symlinks=False)


def allocated_bytes(st: os.stat_result) -> int:
    """What a file occupies on disk, never more than its length.

    ``st_blocks`` is the truth for sparse files (``Docker.raw`` is 80 GB long and
    occupies what Docker has written), and rounds a small file up to a block, so
    the length caps it. Zero blocks means nothing is allocated: a file that is all
    hole, or one evicted to iCloud. Only a platform with no ``st_blocks`` at all
    falls back to the length.
    """
    blocks: int | None = getattr(st, "st_blocks", None)
    if blocks is None:
        return st.st_size
    return min(st.st_size, blocks * 512)


_Hardlinks = dict[tuple[int, int], tuple[int, int, list[str]]]


def _seen_before(hardlinks: _Hardlinks, st: os.stat_result, allocated: int, path: str) -> bool:
    """Record one more name for a multiply-linked file; True when its bytes are counted."""
    key = (st.st_dev, st.st_ino)
    current = hardlinks.get(key)
    if current is not None:
        current[2].append(path)
        return True
    hardlinks[key] = (allocated, st.st_nlink, [path])
    return False


def _records(hardlinks: _Hardlinks) -> tuple[HardlinkRecord, ...]:
    return tuple(
        HardlinkRecord(
            device=device,
            inode=inode,
            allocated_bytes=allocated,
            link_count=link_count,
            paths=tuple(sorted(set(paths))),
        )
        for (device, inode), (allocated, link_count, paths) in sorted(hardlinks.items())
    )


def _walk(root: Path) -> SizeResult:
    skipped: list[Path] = []
    try:
        root_stat = root.lstat()
    except OSError:
        return SizeResult(0, (root,), ())

    # Only a file with more than one name can be met twice, so only those are tracked.
    hardlinks: _Hardlinks = {}
    if stat_mod.S_ISREG(root_stat.st_mode):
        # A path provider may name a file (a model, a disk image) rather than a directory.
        allocated = allocated_bytes(root_stat)
        if root_stat.st_nlink > 1:
            _seen_before(hardlinks, root_stat, allocated, os.fspath(root))
        return SizeResult(
            allocated,
            (),
            _records(hardlinks),
            apparent_bytes=root_stat.st_size,
            newest_mtime=root_stat.st_mtime,
        )

    root_dev = root_stat.st_dev
    newest = root_stat.st_mtime
    total = 0
    apparent = 0
    # Plain strings and one stat per entry: a Path per file cost a third of the walk.
    pending = [os.fspath(root)]
    while pending:
        directory = pending.pop()
        try:
            listing = os.scandir(directory)
        except OSError:
            skipped.append(Path(directory))
            continue
        with listing:
            for entry in listing:
                try:
                    # Follows symlinks, as os.walk does: a link to a directory is a
                    # directory that is never entered, not a file to be counted.
                    is_dir = entry.is_dir()
                except OSError:
                    is_dir = False
                if is_dir and entry.is_symlink():
                    continue
                try:
                    st = _lstat(entry)
                except OSError:
                    skipped.append(Path(entry.path))
                    continue
                if is_dir:
                    if st.st_dev == root_dev:
                        newest = max(newest, st.st_mtime)
                        pending.append(entry.path)
                    continue
                newest = max(newest, st.st_mtime)
                allocated = allocated_bytes(st)
                if st.st_nlink > 1 and _seen_before(hardlinks, st, allocated, entry.path):
                    continue
                total += allocated
                apparent += st.st_size

    return SizeResult(
        total, tuple(skipped), _records(hardlinks), apparent_bytes=apparent, newest_mtime=newest
    )
