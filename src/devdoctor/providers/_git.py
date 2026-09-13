"""Git plumbing for providers that inspect repositories.

This module owns how DevDoctor talks to git: the parsers for the output formats
the git worktree provider reads and, from Task 3 onward, the argv, environment,
timeout and failure handling every git call uses. It knows nothing about
providers, entries or risk.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# `git merge-tree --write-tree` first shipped in git 2.38. Older git falls back to
# `merge-base --is-ancestor` (spec §4.4).
MERGE_TREE_MIN_VERSION: tuple[int, int, int] = (2, 38, 0)

_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)(?:\.(\d+))?")
_BRANCH_REF_PREFIX = "refs/heads/"


def parse_git_version(output: str) -> tuple[int, int, int] | None:
    """Parse ``git version`` output such as ``git version 2.50.1 (Apple Git-155)``."""
    match = _VERSION_RE.match(output.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def supports_merge_tree_write_tree(version: tuple[int, int, int] | None) -> bool:
    return version is not None and version >= MERGE_TREE_MIN_VERSION


@dataclass(frozen=True)
class WorktreeRecord:
    """One record from ``git worktree list --porcelain``."""

    path: Path
    head: str | None
    branch: str | None
    detached: bool = False
    bare: bool = False
    locked: bool = False
    lock_reason: str | None = None
    prunable: bool = False
    prunable_reason: str | None = None


def parse_worktree_porcelain(output: str) -> list[WorktreeRecord]:
    """Parse ``git worktree list --porcelain`` into records, in git's order.

    The first record is always the repository's primary worktree. A path follows
    ``worktree `` verbatim, so paths containing spaces survive. Attributes this
    parser does not know are ignored, so newer git versions keep parsing.
    """
    records: list[WorktreeRecord] = []
    for block in output.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line:
                key, _, value = line.partition(" ")
                fields[key] = value
        if "worktree" not in fields:
            continue
        branch = fields.get("branch")
        records.append(
            WorktreeRecord(
                path=Path(fields["worktree"]),
                head=fields.get("HEAD"),
                branch=branch.removeprefix(_BRANCH_REF_PREFIX) if branch else None,
                detached="detached" in fields,
                bare="bare" in fields,
                locked="locked" in fields,
                lock_reason=fields.get("locked") or None,
                prunable="prunable" in fields,
                prunable_reason=fields.get("prunable") or None,
            )
        )
    return records


@dataclass(frozen=True)
class StatusCounts:
    """Counts from ``git status --porcelain``.

    ``modified`` counts every tracked entry with a staged or unstaged change:
    modifications, additions, deletions and renames. ``untracked`` counts ``??``
    entries; an untracked directory is one entry.
    """

    modified: int
    untracked: int

    @property
    def is_clean(self) -> bool:
        return self.modified == 0 and self.untracked == 0


def parse_status_porcelain(output: str) -> StatusCounts:
    modified = 0
    untracked = 0
    for line in output.splitlines():
        if not line:
            continue
        if line.startswith("?? "):
            untracked += 1
        elif not line.startswith("!! "):
            modified += 1
    return StatusCounts(modified=modified, untracked=untracked)
