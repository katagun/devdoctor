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
    NESTED_REPOSITORY = "contains nested repository"
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
class NestedCheck:
    """What a look inside an integrated, clean worktree found (spec §5.1, state 9).

    ``git worktree remove`` deletes ignored nested repositories and worktrees, so a
    worktree holding one is never reclaimable. Paths are relative to the worktree.
    """

    # A nested ``.git`` entry's directory, or a registered worktree inside this one.
    nested: str | None = None
    # A directory that could not be read, so a nested repository cannot be ruled out.
    unreadable: str | None = None

    @property
    def found_nothing(self) -> bool:
        return self.nested is None and self.unreadable is None


@dataclass(frozen=True)
class WorktreeFacts:
    """What is known so far about one registered, present worktree.

    Facts are gathered in spec §5.1 order and later ones stay ``None`` until needed:
    ``integration`` is only checked once the default branch is known, ``status``
    only once the worktree is known to be integrated, and ``nesting`` only once it
    is also clean. ``failure`` records the first git call that failed.

    ``ownership_ok`` is whether the directory was shown to still belong to its
    registered worktree. When it is false, ``failure`` says whether git could not
    answer (a git error) or answered that it does not (a broken pointer).
    """

    ownership_ok: bool
    locked: bool
    default_branch: str | None
    failure: str | None = None
    integration: Integration | None = None
    status: StatusCounts | None = None
    nesting: NestedCheck | None = None


# One return per state keeps the code in the spec's first-match order.
def classify(facts: WorktreeFacts) -> WorktreeState | None:  # noqa: PLR0911
    """Return the first matching state (spec §5.1), or ``None`` if more facts are needed."""
    if not facts.ownership_ok:
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
    if not facts.status.is_clean:
        return WorktreeState.DIRTY
    if facts.nesting is None:
        return None
    if not facts.nesting.found_nothing:
        return WorktreeState.NESTED_REPOSITORY
    return WorktreeState.INTEGRATED


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
    nesting: NestedCheck | None = None,
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
        if status is None:
            raise ValueError("advice for uncommitted changes needs the status counts")
        message = (
            f"Integrated into {default_branch}, but has {status.modified} modified and "
            f"{status.untracked} untracked files. Commit, stash or discard them first."
        )
    elif state is WorktreeState.NESTED_REPOSITORY:
        message = _nested_message(nesting)
    elif state is WorktreeState.UNVERIFIABLE:
        message = (
            "Inside a worktree folder, but not a registered git worktree. DevDoctor "
            "cannot verify what it contains."
        )
    else:
        raise ValueError(f"{state.value} is not an advice state")
    return message


def _nested_message(nesting: NestedCheck | None) -> str:
    if nesting is not None and nesting.nested is not None:
        return (
            f"Contains another git repository or worktree at {nesting.nested}. git worktree "
            "remove would delete it, including uncommitted work. Move or remove it first."
        )
    if nesting is not None and nesting.unreadable is not None:
        return (
            f"Could not read {nesting.unreadable} inside this worktree, so DevDoctor cannot "
            "rule out a nested repository that git worktree remove would delete."
        )
    raise ValueError("advice for a nested repository needs what the nested check found")
