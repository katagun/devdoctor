"""Linked git worktrees, reclaimable once integrated into the default branch and clean.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from devdoctor.ports import Shell
from devdoctor.providers._git import (
    GitRunner,
    WorktreeRecord,
    read_worktree_pointer,
    supports_merge_tree_write_tree,
    supports_worktree_list_z,
)
from devdoctor.providers._git_queries import (
    DefaultBranch,
    GitQueryError,
    MergeTreeContext,
    check_integration,
    common_git_dir,
    head_commit_times,
    is_partial_clone,
    list_worktrees,
    resolve_default_branch,
    toplevel_matches,
    worktree_status,
)
from devdoctor.providers._worktree_states import (
    WorktreeFacts,
    WorktreeState,
    advice_message,
    classify,
    worktree_label,
)
from devdoctor.providers.base import Provider, _stat_kwargs
from devdoctor.providers.project_artifacts import GitCandidates, ProjectArtifactIndex
from devdoctor.sizer import size_path_detailed
from devdoctor.types import (
    AdviceAction,
    CommandAction,
    DiskUsage,
    Entry,
    Risk,
    render_cleanup_action,
)

# Every check is an independent subprocess, so worktrees classify in parallel (spec §4.2).
WORKER_THREADS = 4


@dataclass(frozen=True)
class _Repository:
    """Facts computed once per repository (spec §4.2 step 3)."""

    path: Path
    default: DefaultBranch | None
    merge_tree: MergeTreeContext | None
    # None when the batched `git log` failed.
    head_times: dict[str, float] | None


class GitWorktreeProvider(Provider):
    name = "git-worktrees"
    family = "vcs"
    description = "Linked git worktrees already integrated into the default branch"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "git"
    details = (
        "Lists the linked worktrees of repositories found under the project roots. A clean "
        "worktree whose changes are already in the default branch is removable with "
        "`git worktree remove`; every other worktree is advice-only. Never fetches."
    )

    def __init__(self, shell: Shell, *, index: ProjectArtifactIndex | None = None) -> None:
        super().__init__(shell)
        self._index = index or ProjectArtifactIndex()
        self._git = GitRunner(shell)

    def discover(self) -> list[Entry]:
        version = self._git.version()
        if not supports_worktree_list_z(version):
            found = "the git version" if version is None else "git " + ".".join(map(str, version))
            self.diagnostics.append(
                f"git-worktrees: worktree listing needs git 2.36 and {found} could not be "
                "confirmed to support it; no worktrees reported"
            )
            return []
        objects_dir = (
            self._create_objects_dir() if supports_merge_tree_write_tree(version) else None
        )
        try:
            return self._discover(self._index.git_candidates(), objects_dir)
        finally:
            if objects_dir is not None:
                self._remove_objects_dir(objects_dir)

    def _discover(self, candidates: GitCandidates, objects_dir: Path | None) -> list[Entry]:
        listed: set[str] = set()
        failed: set[str] = set()
        work: list[tuple[_Repository, WorktreeRecord]] = []
        for repository in _repositories(candidates):
            try:
                records = list_worktrees(self._git, repository)
            except GitQueryError as exc:
                failed.add(_real(repository))
                self.diagnostics.append(
                    f"git-worktrees: git worktree list failed for {repository}: {exc}"
                )
                continue
            listed.update(_real(record.path) for record in records)
            linked = self._linked_worktrees(repository, records)
            if linked:
                facts = self._repository_facts(repository, linked, objects_dir)
                work.extend((facts, record) for record in linked)
        with ThreadPoolExecutor(max_workers=WORKER_THREADS) as pool:
            entries = list(pool.map(lambda item: self._worktree_entry(*item), work))
        entries.extend(self._unverifiable_entries(candidates, listed, failed))
        return entries

    def _linked_worktrees(
        self, repository: Path, records: list[WorktreeRecord]
    ) -> list[WorktreeRecord]:
        """Drop states 1 and 2 (spec §5.1): the primary, bare, prunable and missing."""
        linked: list[WorktreeRecord] = []
        stale = 0
        for record in records[1:]:
            if record.bare:
                continue
            try:
                is_dir = stat.S_ISDIR(record.path.stat().st_mode)
            except (FileNotFoundError, NotADirectoryError):
                is_dir = False
            except OSError as exc:
                self.diagnostics.append(
                    f"git-worktrees: could not access registered worktree {record.path} "
                    f"({exc.strerror}); not reported"
                )
                continue
            if record.prunable or not is_dir:
                stale += 1
                continue
            linked.append(record)
        if stale:
            self.diagnostics.append(
                f"git-worktrees: {stale} registered worktree(s) of {repository} no longer "
                f'exist; run "git -C {repository} worktree prune"'
            )
        return linked

    def _repository_facts(
        self, repository: Path, linked: list[WorktreeRecord], objects_dir: Path | None
    ) -> _Repository:
        default = resolve_default_branch(self._git, repository)
        merge_tree: MergeTreeContext | None = None
        if (
            default is not None
            and objects_dir is not None
            and not is_partial_clone(self._git, repository)
        ):
            try:
                merge_tree = MergeTreeContext(objects_dir, common_git_dir(self._git, repository))
            except GitQueryError as exc:
                self.diagnostics.append(
                    f"git-worktrees: could not resolve the git directory of {repository} "
                    f"({exc}); checking integration with merge-base --is-ancestor"
                )
        head_times: dict[str, float] | None
        try:
            head_times = head_commit_times(
                self._git, repository, [record.head for record in linked if record.head]
            )
        except GitQueryError as exc:
            head_times = None
            self.diagnostics.append(
                f"git-worktrees: could not read HEAD commit times for {repository}: {exc}"
            )
        return _Repository(repository, default, merge_tree, head_times)

    def _classify(
        self, repository: _Repository, record: WorktreeRecord
    ) -> tuple[WorktreeState, WorktreeFacts]:
        """Gather facts in spec §5.1 order until one state matches."""
        default = repository.default
        facts = WorktreeFacts(
            toplevel_ok=toplevel_matches(self._git, record.path),
            locked=record.locked,
            default_branch=default.name if default else None,
        )
        state = classify(facts)
        if state is not None or default is None:
            return _settled(state), facts
        try:
            if record.head is None:
                raise GitQueryError("HEAD is unknown")
            integration = check_integration(
                self._git,
                repository.path,
                default=default,
                head=record.head,
                merge_tree=repository.merge_tree,
            )
            facts = replace(facts, integration=integration)
            state = classify(facts)
            if state is None:
                facts = replace(facts, status=worktree_status(self._git, record.path))
                state = classify(facts)
        except GitQueryError as exc:
            facts = replace(facts, failure=str(exc))
            state = classify(facts)
        return _settled(state), facts

    def _worktree_entry(self, repository: _Repository, record: WorktreeRecord) -> Entry:
        state, facts = self._classify(repository, record)
        label = worktree_label(
            repository_name=repository.path.name,
            directory=record.path,
            state=state,
            branch=record.branch,
            head=record.head,
            detached=record.detached,
        )
        mtime = None
        if repository.head_times is not None and record.head:
            mtime = repository.head_times.get(record.head)
        if state is WorktreeState.INTEGRATED:
            return self._reclaimable_entry(repository.path, record.path, label, mtime)
        gitdir = None
        if state is WorktreeState.BROKEN_POINTER:
            pointer = read_worktree_pointer(record.path)
            gitdir = pointer.gitdir if pointer else record.path / ".git"
        message = advice_message(
            state,
            repository=repository.path,
            gitdir=gitdir,
            lock_reason=record.lock_reason,
            default_branch=facts.default_branch,
            failure=facts.failure,
            status=facts.status,
        )
        return self._advice_entry(record.path, label, mtime, message)

    def _unverifiable_entries(
        self, candidates: GitCandidates, listed: set[str], failed: set[str]
    ) -> list[Entry]:
        """Worktree-folder children and pointers no repository lists (spec §4.2 step 5)."""
        owners: dict[str, tuple[Path, Path]] = {}
        for pointer in candidates.pointers:
            owners.setdefault(_real(pointer.path), (pointer.path, pointer.repository))
        for child in candidates.folder_children:
            owners.setdefault(_real(child), (child, _folder_owner(child)))
        entries: list[Entry] = []
        for key, (directory, owner) in owners.items():
            # A repository whose listing failed has already been reported as a diagnostic.
            if key in listed or key in failed or _real(owner) in failed:
                continue
            try:
                mtime: float | None = directory.lstat().st_mtime
            except OSError:
                mtime = None
            label = worktree_label(
                repository_name=owner.name,
                directory=directory,
                state=WorktreeState.UNVERIFIABLE,
            )
            message = advice_message(WorktreeState.UNVERIFIABLE, repository=owner)
            entries.append(self._advice_entry(directory, label, mtime, message))
        return entries

    def _reclaimable_entry(
        self, repository: Path, path: Path, label: str, mtime: float | None
    ) -> Entry:
        # Never --force: git re-checks the worktree when the cleanup runs (spec §5.3).
        action = CommandAction(("git", "-C", str(repository), "worktree", "remove", str(path)))
        sizing = size_path_detailed(path)
        self._note_skipped(list(sizing.skipped_paths))
        size = sizing.allocated_bytes
        return Entry(
            provider=self.name,
            id=str(path),
            path=path,
            label=label,
            size_bytes=size,
            mtime=mtime,
            risk=Risk.RECLAIMABLE,
            recipe=[render_cleanup_action(action)],
            usage=DiskUsage(size, size),
            actions=(action,),
            hardlinks=sizing.hardlinks,
            **_stat_kwargs(path),
        )

    def _advice_entry(self, path: Path, label: str, mtime: float | None, message: str) -> Entry:
        # Advice entries are never sized (spec §5.2).
        return Entry(
            provider=self.name,
            id=str(path),
            path=path,
            label=label,
            size_bytes=0,
            mtime=mtime,
            risk=Risk.DANGEROUS,
            recipe=[],
            usage=DiskUsage(None, None),
            actions=(AdviceAction(message),),
            **_stat_kwargs(path),
        )

    def _create_objects_dir(self) -> Path | None:
        try:
            return Path(tempfile.mkdtemp(prefix="devdoctor-merge-tree-"))
        except OSError as exc:
            self.diagnostics.append(
                f"git-worktrees: could not create a temporary object directory ({exc}); "
                "checking integration with merge-base --is-ancestor"
            )
            return None

    def _remove_objects_dir(self, path: Path) -> None:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            self.diagnostics.append(
                f"git-worktrees: could not remove temporary object directory {path}: {exc}"
            )


def _repositories(candidates: GitCandidates) -> list[Path]:
    """Distinct repositories: roots the walk found, and those named by intact pointers."""
    seen: set[str] = set()
    repositories: list[Path] = []
    named = (pointer.repository for pointer in candidates.pointers if not pointer.broken)
    for path in (*candidates.repositories, *named):
        key = _real(path)
        if key not in seen:
            seen.add(key)
            repositories.append(path)
    return repositories


def _folder_owner(child: Path) -> Path:
    """The project owning a worktree folder: the parent of ``.worktrees`` or ``.claude``."""
    folder = child.parent
    return folder.parent.parent if folder.name == "worktrees" else folder.parent


def _real(path: Path) -> str:
    return os.path.realpath(path)


def _settled(state: WorktreeState | None) -> WorktreeState:
    if state is None:
        raise AssertionError("classification finished without a state")
    return state
