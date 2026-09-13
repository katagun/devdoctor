"""Git worktree containment: count bytes inside a removable worktree once.

A reclaimable git worktree's removal deletes everything inside it, including
``node_modules``, virtualenvs and build output that other providers report on
their own. Without containment those bytes would be counted twice and offered
for cleanup twice.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §6
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from devdoctor.types import Entry, Risk, ScanFilters, entry_matches_filters

WORKTREE_PROVIDER = "git-worktrees"


def contain_worktree_contents(entries: list[Entry], filters: ScanFilters) -> list[Entry]:
    """Remove entries that lie inside a reclaimable worktree the view shows (spec §6.2).

    An owner is a reclaimable ``git-worktrees`` entry that passes ``filters``. An entry
    hidden because of an owner therefore always has that owner visible in the same
    view, and an owner filtered out of the view hides nothing.
    """
    owners = [
        entry
        for entry in entries
        if _is_owner(entry)
        and entry_matches_filters(
            entry,
            risks=filters.risks,
            min_size=filters.min_size_bytes,
            providers=filters.providers,
        )
    ]
    return _without_contents(entries, owners)


def drop_contents_of_selected_worktrees(selected: list[Entry]) -> list[Entry]:
    """Drop selected entries that removing a selected reclaimable worktree deletes (§6.4).

    Keeping them would run a cleanup for content the worktree removal already
    deletes, and report its bytes as freed twice.
    """
    return _without_contents(selected, [entry for entry in selected if _is_owner(entry)])


def _is_owner(entry: Entry) -> bool:
    return (
        entry.provider == WORKTREE_PROVIDER
        and entry.risk is Risk.RECLAIMABLE
        and entry.path is not None
    )


def _without_contents(entries: list[Entry], owners: Iterable[Entry]) -> list[Entry]:
    roots = {os.path.realpath(owner.path) for owner in owners if owner.path is not None}
    if not roots:
        return list(entries)
    return [
        entry
        for entry in entries
        if entry.provider == WORKTREE_PROVIDER
        or entry.path is None
        or not _inside_any(os.path.realpath(entry.path), roots)
    ]


def _inside_any(path: str, roots: set[str]) -> bool:
    """Whether ``path`` equals or lies inside one of ``roots`` (all realpaths)."""
    current = path
    while True:
        if current in roots:
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent
