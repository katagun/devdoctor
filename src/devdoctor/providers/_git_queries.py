"""Read-only repository queries for the git worktree provider.

Every query runs through ``GitRunner`` under the invocation contract (spec §4.3).
A query that cannot answer raises ``GitQueryError`` with a one-line reason. None of
them writes to a repository.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from devdoctor.providers._git import (
    GitResult,
    GitRunner,
    StatusCounts,
    WorktreeRecord,
    merge_tree_env,
    parse_status_porcelain,
    parse_worktree_porcelain,
)
from devdoctor.providers._worktree_states import Integration

# Tried in order after origin/HEAD (spec §4.4). Always full ref names: a short name
# such as "origin/main" also matches a tag or local branch of that name first.
DEFAULT_BRANCH_FALLBACKS: tuple[str, ...] = (
    "refs/remotes/origin/main",
    "refs/remotes/origin/master",
)
_REMOTE_REFS = "refs/remotes/"

# Commits per batched `git log`, keeping argv far below the platform limit (spec §4.2).
HEAD_TIMES_CHUNK = 500

_OID_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_FALSE_VALUES = frozenset({"false", "no", "off", "0"})


class GitQueryError(Exception):
    """A query could not answer. The message is one line, for advice and diagnostics."""

    @classmethod
    def from_result(cls, result: GitResult) -> GitQueryError:
        return cls(result.failure_summary())


@dataclass(frozen=True)
class DefaultBranch:
    name: str  # for display, such as "origin/main"; never passed to git
    commit: str  # the commit the ref pointed at when resolved
    tree: str  # that commit's tree


@dataclass(frozen=True)
class MergeTreeContext:
    """Where merge-tree may write (a scan's temporary directory) and read from."""

    objects_dir: Path
    common_git_dir: Path


def list_worktrees(git: GitRunner, repository: Path) -> list[WorktreeRecord]:
    result = git.run(repository, ["worktree", "list", "--porcelain", "-z"])
    if not result.ok:
        raise GitQueryError.from_result(result)
    return parse_worktree_porcelain(result.stdout)


def resolve_default_branch(git: GitRunner, repository: Path) -> DefaultBranch | None:
    """``origin/HEAD``, then ``origin/main``, then ``origin/master`` (spec §4.4).

    Each candidate is an exact remote-tracking ref: ``show-ref --verify`` reads only
    that ref, where ``rev-parse`` would also accept a tag named after it. A candidate
    counts only if it names a commit, so a dangling ``origin/HEAD`` falls through to
    the next candidate. Later checks use the commit id, never the name.
    """
    candidates: list[str] = []
    symbolic = git.run(repository, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    target = symbolic.stdout.strip()
    if symbolic.ok and target.startswith(_REMOTE_REFS):
        candidates.append(target)
    candidates.extend(ref for ref in DEFAULT_BRANCH_FALLBACKS if ref not in candidates)
    for ref in candidates:
        commit = _peel(git, repository, ref)
        if commit is None:
            continue
        tree = _rev_parse(git, repository, f"{commit}^{{tree}}")
        if tree is not None:
            return DefaultBranch(name=ref.removeprefix(_REMOTE_REFS), commit=commit, tree=tree)
    return None


def _peel(git: GitRunner, repository: Path, ref: str) -> str | None:
    """The commit ``ref`` points at, or None if that exact ref names no commit."""
    result = git.run(repository, ["show-ref", "--verify", "--hash", ref])
    target = result.stdout.strip()
    if not result.ok or not _OID_RE.fullmatch(target):
        return None
    return _rev_parse(git, repository, f"{target}^{{commit}}")


def _rev_parse(git: GitRunner, repository: Path, revision: str) -> str | None:
    result = git.run(repository, ["rev-parse", "--verify", "--quiet", revision])
    oid = result.stdout.strip()
    return oid if result.ok and _OID_RE.fullmatch(oid) else None


def is_partial_clone(git: GitRunner, repository: Path) -> bool:
    """Whether any remote is a promisor or ``extensions.partialClone`` is set.

    When git cannot answer, the repository counts as a partial clone: that only
    selects the ``is-ancestor`` fallback, which never over-reports integration.
    """
    result = git.run(
        repository,
        ["config", "--get-regexp", r"^(remote\..*\.promisor|extensions\.partialclone)$"],
    )
    if result.returncode == 1:  # no matching keys
        return False
    if not result.ok:
        return True
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        if key == "extensions.partialclone":
            if value:
                return True
        elif value.lower() not in _FALSE_VALUES:  # a bare `promisor` key means true
            return True
    return False


def common_git_dir(git: GitRunner, repository: Path) -> Path:
    result = git.run(repository, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    path = result.stdout.rstrip("\n")
    if not result.ok or not path:
        raise GitQueryError.from_result(result)
    return Path(path)


def head_commit_times(git: GitRunner, repository: Path, heads: Iterable[str]) -> dict[str, float]:
    """Committer time of each commit, from ``git log --no-walk`` batches (spec §4.2).

    The all-zero id of an unborn branch is skipped. Any other unknown commit fails
    its whole batch, and the query raises.
    """
    commits = sorted({head for head in heads if _OID_RE.fullmatch(head) and head.strip("0")})
    times: dict[str, float] = {}
    for start in range(0, len(commits), HEAD_TIMES_CHUNK):
        batch = commits[start : start + HEAD_TIMES_CHUNK]
        result = git.run(repository, ["log", "--no-walk=unsorted", "--format=%H %ct", *batch, "--"])
        if not result.ok:
            raise GitQueryError.from_result(result)
        for line in result.stdout.splitlines():
            commit, _, stamp = line.partition(" ")
            if stamp.isdigit():
                times[commit] = float(stamp)
    return times


def check_integration(
    git: GitRunner,
    repository: Path,
    *,
    default: DefaultBranch,
    head: str,
    merge_tree: MergeTreeContext | None,
) -> Integration:
    """Whether merging ``head`` into the default branch would change nothing (spec §4.4).

    With a ``MergeTreeContext`` this runs ``merge-tree --write-tree``, whose object
    writes land in the context's directory. Without one it runs
    ``merge-base --is-ancestor``, which detects only true merges and fast-forwards.
    """
    if merge_tree is None:
        result = git.run(repository, ["merge-base", "--is-ancestor", head, default.commit])
        if result.returncode == 0:
            return Integration.INTEGRATED
        if result.returncode == 1:
            return Integration.NOT_INTEGRATED
        raise GitQueryError.from_result(result)
    result = git.run(
        repository,
        ["merge-tree", "--write-tree", default.commit, head],
        extra_env=merge_tree_env(merge_tree.objects_dir, merge_tree.common_git_dir),
    )
    tree = result.stdout.partition("\n")[0]
    # Exit 1 with a tree on the first line is a conflicted merge. Exit 1 without one is
    # an error, such as a revision git cannot find.
    if result.returncode not in (0, 1) or not _OID_RE.fullmatch(tree):
        raise GitQueryError.from_result(result)
    if result.returncode == 0 and tree == default.tree:
        return Integration.INTEGRATED
    return Integration.NOT_INTEGRATED


def toplevel_matches(git: GitRunner, worktree: Path) -> bool:
    """Whether git resolves ``worktree`` to itself. False for a broken ``.git`` pointer."""
    result = git.run(worktree, ["rev-parse", "--show-toplevel"])
    toplevel = result.stdout.rstrip("\n")
    return result.ok and bool(toplevel) and os.path.realpath(toplevel) == os.path.realpath(worktree)


def worktree_status(git: GitRunner, worktree: Path) -> StatusCounts:
    result = git.run(worktree, ["status", "--porcelain", "--untracked-files=normal"])
    if not result.ok:
        raise GitQueryError.from_result(result)
    return parse_status_porcelain(result.stdout)
