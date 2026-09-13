"""States, labels and advice for classified git worktrees.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path

from devdoctor.providers._git import StatusCounts


class WorktreeState(StrEnum):
    """How a worktree is classified. Each value is the state text used in labels."""

    INTEGRATED = "integrated"
    DIRTY = "integrated, uncommitted changes"
    NOT_INTEGRATED = "not integrated"
    BROKEN_POINTER = "broken pointer"
    LOCKED = "locked"
    NO_DEFAULT_BRANCH = "no default branch"
    GIT_ERROR = "git error"
    UNVERIFIABLE = "unverifiable"


class Integration(Enum):
    INTEGRATED = "integrated"
    NOT_INTEGRATED = "not integrated"


@dataclass(frozen=True)
class WorktreeFacts:
    """What is known so far about one registered, present worktree.

    Facts are gathered in spec §5.1 order and later ones stay ``None`` until needed:
    ``integration`` is only checked once the default branch is known, and
    ``status`` only once the worktree is known to be integrated. ``failure`` records
    the first git call that failed.

    ``toplevel_ok`` is whether the directory was shown to still belong to its
    registered worktree. When it is false, ``failure`` says whether git could not
    answer (a git error) or answered that it does not (a broken pointer).
    """

    toplevel_ok: bool
    locked: bool
    default_branch: str | None
    failure: str | None = None
    integration: Integration | None = None
    status: StatusCounts | None = None


# One return per state keeps the code in the spec's first-match order.
def classify(facts: WorktreeFacts) -> WorktreeState | None:  # noqa: PLR0911
    """Return the first matching state (spec §5.1), or ``None`` if more facts are needed."""
    if not facts.toplevel_ok:
        return WorktreeState.BROKEN_POINTER if facts.failure is None else WorktreeState.GIT_ERROR
    if facts.locked:
        return WorktreeState.LOCKED
    if facts.default_branch is None:
        return WorktreeState.NO_DEFAULT_BRANCH
    if facts.failure is not None:
        return WorktreeState.GIT_ERROR
    if facts.integration is None:
        return None
    if facts.integration is Integration.NOT_INTEGRATED:
        return WorktreeState.NOT_INTEGRATED
    if facts.status is None:
        return None
    return WorktreeState.INTEGRATED if facts.status.is_clean else WorktreeState.DIRTY


def worktree_label(
    *,
    repository_name: str,
    directory: Path,
    state: WorktreeState,
    branch: str | None = None,
    head: str | None = None,
    detached: bool = False,
) -> str:
    """``<repository>/<directory> · [branch | detached @sha] · <state>`` (spec §5.2)."""
    parts = [f"{repository_name}/{directory.name}"]
    if detached and head:
        parts.append(f"detached @{head[:7]}")
    elif branch and branch != directory.name:
        parts.append(branch)
    parts.append(state.value)
    return " · ".join(parts)


def advice_message(
    state: WorktreeState,
    *,
    repository: Path,
    gitdir: Path | None = None,
    lock_reason: str | None = None,
    default_branch: str | None = None,
    failure: str | None = None,
    status: StatusCounts | None = None,
) -> str:
    """The advice text for an advice-only state (spec §5.2).

    For a broken pointer, ``gitdir`` is the missing git directory a ``.git`` file
    names; without one, the ``.git`` does not point back to ``repository``.
    """
    if state is WorktreeState.BROKEN_POINTER and gitdir is not None:
        message = (
            f"This worktree's .git file points to {gitdir}, which does not exist; the "
            f'repository was probably moved. Run "git -C {repository} worktree repair", '
            "then rescan."
        )
    elif state is WorktreeState.BROKEN_POINTER:
        message = (
            f"This worktree's .git does not point back to {repository}. Run "
            f'"git -C {repository} worktree repair", then rescan.'
        )
    elif state is WorktreeState.LOCKED:
        message = f"Locked by git: {lock_reason}." if lock_reason else "Locked by git."
    elif state is WorktreeState.NO_DEFAULT_BRANCH:
        message = (
            f"Cannot determine the default branch of {repository}: no origin/HEAD, "
            "origin/main or origin/master."
        )
    elif state is WorktreeState.GIT_ERROR:
        message = f"git failed while checking this worktree: {failure}."
    elif state is WorktreeState.NOT_INTEGRATED:
        message = (
            f"Not integrated into {default_branch}. Anything inside it that other "
            "providers report can still be cleaned individually."
        )
    elif state is WorktreeState.DIRTY:
        modified = status.modified if status else 0
        untracked = status.untracked if status else 0
        message = (
            f"Integrated into {default_branch}, but has {modified} modified and "
            f"{untracked} untracked files. Commit, stash or discard them first."
        )
    elif state is WorktreeState.UNVERIFIABLE:
        message = (
            "Inside a worktree folder, but not a registered git worktree. DevDoctor "
            "cannot verify what it contains."
        )
    else:
        raise ValueError(f"{state.value} is not an advice state")
    return message
