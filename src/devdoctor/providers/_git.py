"""Git plumbing for providers that inspect repositories.

This module owns how DevDoctor talks to git: the argv, environment, timeout and
failure handling every git call uses, and parsers for the output formats the git
worktree provider reads. It knows nothing about providers, entries or risk.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from devdoctor.ports import Shell

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


# Every git call is bounded, so one hung repository cannot stall a scan (spec §4.3).
GIT_CALL_TIMEOUT_S = 30.0

# Set on every git call: never prompt for credentials, and never fetch missing
# objects from a promisor remote. Applied last, so no caller can switch them off.
_OFFLINE_ENV: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}


def git_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment for one git call: ``extra`` plus the offline guards, which win."""
    return {**(extra or {}), **_OFFLINE_ENV}


def merge_tree_env(temp_objects_dir: Path, common_git_dir: Path) -> dict[str, str]:
    """Extra environment that sends ``git merge-tree``'s object writes to a temp dir.

    Reads still resolve through the repository's own object store. Only merge-tree
    may use this; every other call needs the real object store (spec §4.3).
    """
    return {
        "GIT_OBJECT_DIRECTORY": str(temp_objects_dir),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(common_git_dir / "objects"),
    }


@dataclass(frozen=True)
class GitResult:
    """The outcome of one git call. Failures are values, never exceptions."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    timeout_s: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def failure_summary(self) -> str:
        """One line describing a failure, for advice messages (spec §5.2)."""
        if self.timed_out:
            return f"timed out after {self.timeout_s:g} s"
        for line in self.stderr.splitlines():
            if line.strip():
                return line.strip()
        return f"exit {self.returncode}"


class GitRunner:
    """Runs git through the ``Shell`` port under the invocation contract (spec §4.3)."""

    def __init__(self, shell: Shell, *, timeout_s: float = GIT_CALL_TIMEOUT_S) -> None:
        self._shell = shell
        self._timeout_s = timeout_s

    def run(
        self,
        directory: Path,
        args: Sequence[str],
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> GitResult:
        argv = ["git", "--no-optional-locks", "-C", str(directory), *args]
        try:
            result = self._shell.run(
                argv,
                check=False,
                timeout=self._timeout_s,
                env=git_env(extra_env),
            )
        except subprocess.TimeoutExpired:
            return GitResult(None, "", "", timed_out=True, timeout_s=self._timeout_s)
        except OSError as exc:
            # git vanished or could not be launched: still a result, never a crash.
            return GitResult(None, "", str(exc), timed_out=False, timeout_s=self._timeout_s)
        return GitResult(
            result.returncode,
            result.stdout,
            result.stderr,
            timed_out=False,
            timeout_s=self._timeout_s,
        )

    def version(self) -> tuple[int, int, int] | None:
        """The installed git's version, or ``None`` if it cannot be determined."""
        # `version` is not repository-scoped; "/" is a directory that always exists.
        result = self.run(Path("/"), ["version"])
        return parse_git_version(result.stdout) if result.ok else None
