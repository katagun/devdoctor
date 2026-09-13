"""Git plumbing for providers that inspect repositories.

This module owns how DevDoctor talks to git: the argv, environment, timeout and
failure handling every git call uses, and parsers for the output formats the git
worktree provider reads. It knows nothing about providers, entries or risk.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from devdoctor.ports import Shell

# `git merge-tree --write-tree` first shipped in git 2.38. Older git falls back to
# `merge-base --is-ancestor` (spec §4.4).
MERGE_TREE_MIN_VERSION: tuple[int, int, int] = (2, 38, 0)

# `git worktree list --porcelain -z` first shipped in git 2.36. It is the only listing
# that represents every worktree path, so older git lists no worktrees (spec §4.4).
WORKTREE_LIST_Z_MIN_VERSION: tuple[int, int, int] = (2, 36, 0)

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


def supports_worktree_list_z(version: tuple[int, int, int] | None) -> bool:
    return version is not None and version >= WORKTREE_LIST_Z_MIN_VERSION


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
    """Parse ``git worktree list --porcelain -z`` into records, in git's order.

    Every field ends with NUL and an empty field ends a record, so paths and lock
    reasons that contain newlines arrive intact and unquoted. The first record is
    always the repository's primary worktree. Attributes this parser does not know
    are ignored, so newer git versions keep parsing.
    """
    records: list[WorktreeRecord] = []
    fields: dict[str, str] = {}
    for item in output.split("\0"):
        if item:
            key, _, value = item.partition(" ")
            fields[key] = value
            continue
        record = _worktree_record(fields)
        if record is not None:
            records.append(record)
        fields = {}
    final = _worktree_record(fields)  # a last record whose terminator is missing
    if final is not None:
        records.append(final)
    return records


def _worktree_record(fields: dict[str, str]) -> WorktreeRecord | None:
    if "worktree" not in fields:
        return None
    branch = fields.get("branch")
    return WorktreeRecord(
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


@dataclass(frozen=True)
class WorktreePointer:
    """A directory whose ``.git`` is a file naming a linked worktree's git directory."""

    path: Path
    gitdir: Path
    # The owning repository: ``<repo>`` for ``<repo>/.git/worktrees/<name>``, or the
    # bare repository for ``<repo.git>/worktrees/<name>``. Derived from the path even
    # when that path no longer exists.
    repository: Path
    # The gitdir does not exist, typically because the repository was moved.
    broken: bool


def read_worktree_pointer(directory: Path) -> WorktreePointer | None:
    """Parse ``directory/.git`` when it is a file pointing at a linked worktree.

    Submodules and other gitfiles are not worktrees and return None: only a gitdir
    whose parent directory is named ``worktrees`` identifies a linked worktree. A
    relative gitdir resolves against ``directory``.
    """
    dotgit = directory / ".git"
    try:
        if not dotgit.is_file() or dotgit.is_symlink():
            return None
        first_line = dotgit.read_text(encoding="utf-8", errors="replace").partition("\n")[0]
    except OSError:
        return None
    raw = first_line.removeprefix("gitdir:").strip()
    if raw == first_line.strip() or not raw:
        return None
    gitdir = Path(os.path.normpath(raw if os.path.isabs(raw) else directory / raw))
    if gitdir.parent.name != "worktrees":
        return None
    admin = gitdir.parent.parent
    repository = admin.parent if admin.name == ".git" else admin
    return WorktreePointer(
        path=directory,
        gitdir=gitdir,
        repository=repository,
        broken=not os.path.isdir(gitdir),
    )


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
    """Count changes in ``git status --porcelain`` (v1) output.

    Expects the default v1 format without ``-b`` or ``-z``: a ``## branch`` header
    would be counted as a change, and NUL-terminated entries would not be split.
    A conflicted entry such as ``UU path`` counts as modified, so a conflict never
    reads as clean.
    """
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

# Repository-local variables, as listed by `git rev-parse --local-env-vars`. Inherited
# values take precedence over `-C`, so every call removes them (spec §4.3). A real-git
# test fails if the installed git lists a name missing here.
LOCAL_ENV_VARS: tuple[str, ...] = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)

# Set on every git call: never prompt for credentials, and never fetch missing
# objects from a promisor remote. Applied last, so no caller can switch them off.
# Git honours GIT_NO_LAZY_FETCH only from 2.44; older git may still lazy-fetch in a
# partial clone (spec §11).
_OFFLINE_ENV: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}


def git_env(extra: Mapping[str, str] | None = None) -> dict[str, str | None]:
    """The environment changes for one git call, for ``Shell.run(env=...)``.

    Every repository-local variable is removed (``None``), then ``extra`` is applied
    (merge-tree uses it to restore its two object-directory variables), and the offline
    guards are applied last, so no caller can switch them off.
    """
    removed: dict[str, str | None] = dict.fromkeys(LOCAL_ENV_VARS)
    return {**removed, **(extra or {}), **_OFFLINE_ENV}


def merge_tree_env(temp_objects_dir: Path, common_git_dir: Path) -> dict[str, str]:
    """Extra environment that sends ``git merge-tree``'s object writes to a temp dir.

    Reads still resolve through the repository's own object store. Only merge-tree
    may use this; every other call needs the real object store (spec §4.3).
    """
    return {
        "GIT_OBJECT_DIRECTORY": str(temp_objects_dir),
        # Git splits this variable on ":" unless an entry is C-quoted, so always quote.
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": _c_quote(str(common_git_dir / "objects")),
    }


def _c_quote(value: str) -> str:
    """Quote ``value`` the way git unquotes an entry in a path-list variable."""
    escaped: list[str] = []
    for char in value:
        if char in ('"', "\\"):
            escaped.append("\\" + char)
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\t":
            escaped.append("\\t")
        elif char < " " or char == "\x7f":
            escaped.append(f"\\{ord(char):03o}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


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
        """Run ``git --no-optional-locks -C <directory> <args>`` under the contract.

        Repository-local variables inherited from the caller are removed, ``extra_env``
        is applied, and the offline guards win. Timeouts, launch failures and non-zero
        exits come back as ``GitResult`` values; this method never raises for them.
        """
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
