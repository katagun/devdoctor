"""Python virtualenv provider.

Finds ``.venv`` / ``venv`` / ``env`` directories containing a ``pyvenv.cfg``
file across the user's project trees. A rogue pip install can easily leave
hundreds of MB of packages per venv, and stale ones accumulate across every
side project you ever started.

Symlink handling
~~~~~~~~~~~~~~~~
- ``os.walk`` is invoked with ``followlinks=False`` so we never descend into
  a symlinked tree while scanning.
- Every candidate venv is resolved via ``Path.resolve()`` before reporting,
  and deduped by its resolved path. If two projects each symlink ``.venv``
  to the same central location (a common uv / virtualenv-wrapper pattern),
  only one entry is emitted and the recipe points to the real target.
- Within a given venv, ``size_path`` dedupes hard-linked files by
  ``(dev, ino)`` so dist-info hard links from pip cache reuse don't
  double-count.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from diskdoctor.providers.base import Provider, _stat_kwargs
from diskdoctor.sizer import size_path
from diskdoctor.types import Entry, Risk

# Directory basenames that look like venvs. A candidate is only treated as a
# venv if it also contains a ``pyvenv.cfg`` file, which is the PEP 405
# marker file written by both ``python -m venv`` and ``uv venv``.
_VENV_BASENAMES = frozenset({".venv", "venv", "env", ".env"})

# How deep we walk from each scan root. Project trees rarely nest deeper;
# capping keeps the walk O(tractable) on busy home directories.
_MAX_DEPTH = 6

# Names we never recurse into — either managed by another provider, too
# noisy to be interesting, or simply too expensive to walk.
_SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        ".hg",
        ".svn",
        "Library",  # macOS — system-owned, not a project tree
        ".cache",
        "__pycache__",
        ".tox",
        ".nox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",  # Rust / Java
    }
)

# Where to look for projects. Users structure home differently; these are
# the top-level directories most likely to hold code. We never scan the full
# $HOME recursively — too slow and too many false-positive directories.
_SCAN_ROOTS = (
    "~/projects",
    "~/Projects",
    "~/code",
    "~/Code",
    "~/src",
    "~/dev",
    "~/Development",
    "~/work",
    "~/Work",
    "~/repos",
    "~/Repos",
    "~/github",
    "~/workspace",
    "~/Documents",  # some users keep projects here
)


class VenvProvider(Provider):
    name = "python-venvs"
    description = (
        "Python virtualenvs (.venv / venv / env) under common code directories, "
        "one entry per project"
    )
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE  # rebuildable with `uv sync` / `pip install -r`
    required_binary = None

    def discover(self) -> list[Entry]:
        entries: list[Entry] = []
        # Dedup by (dev, ino) instead of resolved string path: this is robust
        # on case-insensitive filesystems (APFS default) where two differently-
        # cased paths point to the same directory but resolve() preserves the
        # casing used by the caller. Inode identity collapses them.
        seen_inodes: set[tuple[int, int]] = set()
        for raw in _SCAN_ROOTS:
            root = Path(os.path.expanduser(raw))
            if not root.exists() or not root.is_dir():
                continue
            try:
                root_dev = root.lstat().st_dev
            except OSError:
                continue
            for venv_dir in _find_venvs(root, root_dev):
                try:
                    real = venv_dir.resolve(strict=True)
                    rst = real.lstat()
                except (OSError, RuntimeError):
                    # Broken symlink or loop — skip cleanly.
                    continue
                key = (rst.st_dev, rst.st_ino)
                if key in seen_inodes:
                    continue
                seen_inodes.add(key)

                size, _ = size_path(real)
                if size == 0:
                    continue
                mtime: float | None = rst.st_mtime

                # Label shows the enclosing project (parent of the venv dir)
                # so "myproj/.venv" is what the user actually recognises.
                project_hint = venv_dir.parent.name
                label = f"{project_hint}/{venv_dir.name}" if project_hint else venv_dir.name

                entries.append(
                    Entry(
                        provider=self.name,
                        id=str(real),
                        path=real,
                        label=label,
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=[f"rm -rf {shlex.quote(str(real))}"],
                        **_stat_kwargs(real),
                    )
                )
        return entries


def _find_venvs(root: Path, root_dev: int) -> list[Path]:
    """Walk `root` up to _MAX_DEPTH levels, yielding venv directories.

    Does not follow symlinks (callers resolve them explicitly for dedup).
    Prunes aggressively: skips known-irrelevant dirs, skips across device
    boundaries, and doesn't descend INTO a venv once one is found (no
    reason to look for `.venv/lib/.venv`).
    """
    hits: list[Path] = []

    def on_error(_err: OSError) -> None:
        return None

    root_depth = len(root.parts)

    for dirpath, dirnames, _filenames in os.walk(root, followlinks=False, onerror=on_error):
        dp = Path(dirpath)
        depth = len(dp.parts) - root_depth
        if depth >= _MAX_DEPTH:
            dirnames[:] = []
            continue

        # Check whether any child looks like a venv; if so, record and prune it.
        keep: list[str] = []
        for name in dirnames:
            sub = dp / name
            if name in _VENV_BASENAMES and (sub / "pyvenv.cfg").is_file():
                hits.append(sub)
                continue  # don't descend into the venv itself
            if name in _SKIP_DIR_NAMES:
                continue
            if name.startswith("."):
                # Hidden dirs other than venv basenames are usually noise
                # (.vscode, .idea, .github, etc.). .venv itself is caught
                # by the check above.
                continue
            try:
                if sub.lstat().st_dev != root_dev:
                    continue  # different filesystem, skip
            except OSError:
                continue
            keep.append(name)
        dirnames[:] = keep

    return hits


__all__ = ["VenvProvider"]
