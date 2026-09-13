"""Find what ``git worktree remove`` would delete that is not the worktree's own work.

git refuses to remove a worktree holding a nested repository only when that
repository is not ignored. Ignored nested repositories and worktrees are deleted
with it, uncommitted work included, and ``git status`` cannot see them.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §5.1, state 9.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from devdoctor.providers._worktree_states import NestedCheck

GIT_ENTRY = ".git"


def check_nesting(worktree: Path, registered: Iterable[str]) -> NestedCheck:
    """Look for a registered worktree, a ``.git`` entry or an unreadable directory inside.

    ``registered`` holds the resolved paths of every worktree the scan listed. The
    walk does not follow symlinks, skips the worktree's own ``.git`` and stops at the
    first finding.
    """
    root = os.path.realpath(worktree)
    inside = sorted(path for path in registered if _strictly_inside(path, root))
    if inside:
        return NestedCheck(nested=os.path.relpath(inside[0], root))
    return _walk(root)


def _walk(root: str) -> NestedCheck:
    unreadable: list[str] = []

    def record(error: OSError) -> None:
        unreadable.append(str(error.filename))

    for directory, dirnames, filenames in os.walk(root, onerror=record):
        if unreadable:
            break
        dirnames.sort()
        if directory == root:
            if GIT_ENTRY in dirnames:
                dirnames.remove(GIT_ENTRY)
            continue
        if GIT_ENTRY in dirnames or GIT_ENTRY in filenames:
            return NestedCheck(nested=os.path.relpath(directory, root))
    if unreadable:
        return NestedCheck(unreadable=os.path.relpath(unreadable[0], root))
    return NestedCheck()


def _strictly_inside(path: str, root: str) -> bool:
    return path != root and path.startswith(root.rstrip(os.sep) + os.sep)
