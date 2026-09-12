"""Shared walk-pruning policy for providers that scan the filesystem.

Dot-directories are deliberately **not** pruned as a class. Every modern agent
and git worktree layout lives behind one — ``.worktrees/``,
``.claude/worktrees/``, ``.codex/`` — and those hold real projects. A blanket
"skip anything starting with a dot" rule makes them structurally invisible.

Pruning is therefore driven by explicit names only. :data:`PRUNE_DIR_NAMES` is
the shared baseline: directories that hold no projects of their own, are owned
by another provider, or are simply too expensive to walk. Providers compose it
with their own additions rather than restating it.
"""

from __future__ import annotations

import os
from pathlib import Path

# Directories no filesystem-walking provider should ever descend into.
# Artifact directories a provider is specifically looking for (node_modules,
# target, dist, build) are deliberately absent: those are per-provider concerns.
PRUNE_DIR_NAMES = frozenset(
    {
        # VCS metadata
        ".git",
        ".hg",
        ".svn",
        # environments and interpreter caches
        ".cache",
        ".venv",
        "venv",
        "__pycache__",
        ".direnv",
        ".eggs",
        # package manager stores
        ".npm",
        ".yarn",
        ".pnpm-store",
        ".node-gyp",
        ".bundle",
        # build output and tool caches
        ".terraform",
        ".terragrunt-cache",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".angular",
        ".turbo",
        ".parcel-cache",
        ".gradle",
        ".dart_tool",
        ".serverless",
        # linter and test caches
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".nyc_output",
        ".tox",
        ".nox",
        # system
        "Library",  # macOS — system-owned, and covered by other providers
        ".Trash",
    }
)

# Directories most likely to hold code. Agent tools keep their scratch checkouts
# outside any of the classic code roots, so those homes are included explicitly:
# on one real machine they held 12.1 GB of node_modules between them.
PROJECT_ROOTS = (
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
    "~/Documents/projects",
    # agent scratch checkouts
    "~/.claude-worktrees",
    "~/.codex/worktrees",
    "~/.cursor/worktrees",
)

# Files that mark the start of a project. Finding one resets the depth budget,
# so a monorepo nested inside a worktree stays reachable without lifting the
# bound globally.
PROJECT_MARKER_FILES = frozenset(
    {
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "build.gradle",
        "build.gradle.kts",
        "pom.xml",
        "Gemfile",
        "composer.json",
    }
)

# How far we walk past the nearest project marker, and the absolute ceiling that
# stops a pathological tree regardless of how many markers it contains.
UNMARKED_DEPTH_BUDGET = 6
MAX_ABSOLUTE_DEPTH = 16


class DepthBudget:
    """Marker-anchored depth accounting for an ``os.walk`` loop.

    A flat depth cap measured from the scan root cannot tell
    ``~/projects/a/b/c/d/e/f`` (genuinely deep junk) from
    ``~/projects/github/org/repo/.worktrees/branch/apps/web`` (a normal monorepo
    two directories into a worktree). This counts distance from the nearest
    enclosing project marker instead, under a hard absolute ceiling.
    """

    def __init__(self, root: Path) -> None:
        self._root_depth = len(root.parts)
        self._pending: dict[str, int] = {}
        self._current = 0

    def allows(self, dirpath: str, dir_parts: int) -> bool:
        """Whether this directory is within budget. Call once per walk step."""
        absolute = dir_parts - self._root_depth
        self._current = self._pending.pop(dirpath, absolute)
        return self._current < UNMARKED_DEPTH_BUDGET and absolute < MAX_ABSOLUTE_DEPTH

    def descend(self, dirpath: str, names: list[str], *, reset: bool) -> None:
        """Record the budget children inherit; ``reset`` when a marker was found."""
        inherited = 0 if reset else self._current + 1
        for name in names:
            self._pending[os.path.join(dirpath, name)] = inherited


__all__ = [
    "MAX_ABSOLUTE_DEPTH",
    "PROJECT_MARKER_FILES",
    "PROJECT_ROOTS",
    "PRUNE_DIR_NAMES",
    "UNMARKED_DEPTH_BUDGET",
    "DepthBudget",
]
