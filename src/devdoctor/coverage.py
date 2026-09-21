"""How much of the disk a scan accounts for, and what it misses (#81).

A scan reports what its providers know about. On the machine that prompted this
it was 90 GB of 396 GB used, and nothing said so: every gap in the provider
catalogue was found by running ``du`` by hand and comparing. Two questions are
answered here.

``summarise`` is the cheap one: classified bytes against the volume's used
bytes. It costs one short ``df`` call and runs on every unfiltered scan.

``unclassified_directories`` is the expensive one: it sizes the home directory
outside every classified path and returns the largest directories nobody
accounts for. That is a walk of everything the scan did *not* walk, so it runs
only when asked for.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from devdoctor.sizer import FileId, allocated_bytes, size_many
from devdoctor.types import Coverage, Entry, Unclassified, unique_footprint_bytes

__all__ = ["Coverage", "Unclassified", "detail", "summarise", "unclassified_directories"]

# Depth 3 under the home directory reaches ~/Library/Application Support/<app>,
# which is where unaccounted space turns out to live; deeper lists noise.
DEFAULT_DEPTH = 3
DEFAULT_LIMIT = 10

DiskUsageFn = Callable[[Path], tuple[int, int, int]]


def summarise(
    entries: Sequence[Entry], home: Path, *, disk_usage: DiskUsageFn | None = None
) -> Coverage | None:
    """Classified footprint against the used space of the volume holding ``home``.

    None when the volume cannot be read: coverage is a courtesy and never fails a scan.
    """
    usage = disk_usage or volume_usage
    try:
        _total, used, _free = usage(_nearest_existing(home))
    except OSError:
        return None
    return Coverage(used_bytes=int(used), classified_bytes=unique_footprint_bytes(list(entries)))


_DF_TIMEOUT_S = 5.0
_DF_NUMBERS = re.compile(r"\s(\d+)\s+(\d+)\s+(\d+)\s+\d+%\s")
_KIB = 1024


def volume_usage(path: Path) -> tuple[int, int, int]:
    """Total, used and free bytes of the volume holding ``path``.

    ``shutil.disk_usage`` derives used space as total minus free. On APFS the total
    is the whole container, so that figure also counts the system, swap and preboot
    volumes: 51 GB that is not this volume's. ``df`` reports the volume's own used
    space on macOS and the same figure as Python on Linux, so it is asked first.
    """
    try:
        result = subprocess.run(
            ["/bin/df", "-Pk", str(path)],
            capture_output=True,
            check=False,
            timeout=_DF_TIMEOUT_S,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
        parsed = _parse_df(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        parsed = None
    if parsed is not None:
        return parsed
    usage = shutil.disk_usage(path)
    return usage.total, usage.used, usage.free


def _parse_df(output: str) -> tuple[int, int, int] | None:
    """Total, used, free from ``df -Pk``; None unless the one data line is readable."""
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 2:  # noqa: PLR2004 - a header and the volume's line
        return None
    # Device and mount point may both contain spaces; the numbers between them cannot.
    match = _DF_NUMBERS.search(lines[1])
    if match is None:
        return None
    total, used, free = (int(value) * _KIB for value in match.groups())
    return total, used, free


def _nearest_existing(path: Path) -> Path:
    """``path`` or its closest ancestor that exists: a fresh or test HOME may not."""
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def detail(
    coverage: Coverage,
    entries: Iterable[Entry],
    home: Path,
    *,
    depth: int = DEFAULT_DEPTH,
    limit: int = DEFAULT_LIMIT,
) -> Coverage:
    """``coverage`` with the largest unclassified directories under ``home`` filled in."""
    found = unclassified_directories(
        home, [entry.path for entry in entries if entry.path is not None], depth=depth, limit=limit
    )
    return Coverage(
        used_bytes=coverage.used_bytes,
        classified_bytes=coverage.classified_bytes,
        unclassified=found.directories,
        skipped=found.skipped,
    )


@dataclass(frozen=True)
class UnclassifiedResult:
    directories: tuple[Unclassified, ...]
    # Paths that could not be read (macOS privacy protection, permissions, vanished).
    skipped: int


def unclassified_directories(
    home: Path, classified: Iterable[Path], *, depth: int, limit: int
) -> UnclassifiedResult:
    """The ``limit`` largest directories under ``home`` that no classified path covers.

    Directories are listed at ``depth`` levels below ``home``, or shallower when they
    have no subdirectories. Files sitting directly in a directory that *is* descended
    are reported against it with ``files_only``, so every byte lands in one row.
    Symlinks are never followed and other devices are never entered.
    """
    root = os.path.realpath(home)
    exclude = _identities(classified)
    try:
        root_dev = os.lstat(root).st_dev
    except OSError:
        return UnclassifiedResult((), 1)

    leaves: list[str] = []
    loose: list[tuple[str, int, bool]] = []  # path, bytes, has subdirectories
    skipped = 0
    pending = [(root, 0)]
    while pending:
        directory, level = pending.pop()
        listed = _list(directory, exclude, root_dev)
        if listed is None:
            skipped += 1
            continue
        skipped += listed.unreadable
        if level + 1 >= depth:
            leaves.extend(listed.subdirectories)
        else:
            pending.extend((path, level + 1) for path in listed.subdirectories)
        if listed.file_bytes:
            loose.append((directory, listed.file_bytes, bool(listed.subdirectories)))

    rows = [Unclassified(Path(path), size, files_only) for path, size, files_only in loose]
    for path, sizing in zip(
        leaves, size_many([Path(leaf) for leaf in leaves], exclude=exclude), strict=True
    ):
        skipped += len(sizing.skipped_paths)
        if sizing.allocated_bytes:
            rows.append(Unclassified(Path(path), sizing.allocated_bytes))
    rows.sort(key=lambda row: (-row.bytes, str(row.path)))
    return UnclassifiedResult(tuple(rows[:limit]), skipped)


@dataclass(frozen=True)
class _Listing:
    file_bytes: int
    subdirectories: tuple[str, ...]
    unreadable: int


def _list(directory: str, exclude: frozenset[FileId], root_dev: int) -> _Listing | None:
    """One directory's own files and its enterable subdirectories; None if unreadable."""
    try:
        listing = os.scandir(directory)
    except OSError:
        return None
    file_bytes = 0
    subdirectories: list[str] = []
    unreadable = 0
    with listing:
        for entry in listing:
            try:
                st = entry.stat(follow_symlinks=False)
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError:
                unreadable += 1
                continue
            if (st.st_dev, st.st_ino) in exclude:
                continue
            if is_directory:
                if st.st_dev == root_dev:
                    subdirectories.append(entry.path)
                continue
            file_bytes += allocated_bytes(st)
    return _Listing(file_bytes, tuple(subdirectories), unreadable)


def _identities(paths: Iterable[Path]) -> frozenset[FileId]:
    """Device and inode of every path that exists; how classified paths are recognised."""
    found: set[FileId] = set()
    for path in paths:
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            continue
        found.add((st.st_dev, st.st_ino))
    return frozenset(found)
