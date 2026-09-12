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

__all__ = ["PRUNE_DIR_NAMES"]
