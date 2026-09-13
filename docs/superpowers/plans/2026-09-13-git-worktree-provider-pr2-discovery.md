# Git Worktree Provider, PR 2: Discovery and Classification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `GitWorktreeProvider`, which finds linked git worktrees and classifies every one into the spec's states, write-free and offline, without registering it.

**Architecture:** The shared project walk also records git candidates: repository roots, `.git` pointer files and worktree-folder children. Classification is split into three private layers, each testable on its own: `_worktree_states.py` (pure state order, labels and advice text), `_git_queries.py` (read-only repository queries on PR 1's `GitRunner`), and `git_worktrees.py` (the provider: one `worktree list` per repository, per-repository facts, a pool of 4 threads classifying worktrees, sizing only the reclaimable ones). `registry.py` is untouched, so nothing is user-visible until PR 3 adds containment.

**Tech Stack:** Python 3.12, pytest, real git (2.36+; merge-tree path 2.38+), ruff, mypy (strict), uv.

**Spec:** `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` — this plan implements §9 PR 2, using §4.2–§4.4, §5, §7 and §8 (layers 1 and 3). Built on PR 1 (#100) and the #98 hardening (#101).

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100`, rules `E, F, I, UP, B, SIM, PL, RUF`; `mypy --strict` over `src/devdoctor`.
- Provider: `name = "git-worktrees"`, `family = "vcs"`, `required_binary = "git"`, `platforms = ("darwin", "linux")`, class-level `risk = Risk.RECLAIMABLE` (entries set their own risk). Receives the shared `ProjectArtifactIndex`. (spec §4.1)
- Not registered: `src/devdoctor/registry.py` is untouched and there is no CHANGELOG entry; both ship in PR 3 with containment. (spec §9)
- Every git call goes through `GitRunner` (`git --no-optional-locks -C <dir>`, local variables removed, `GIT_TERMINAL_PROMPT=0`, `GIT_NO_LAZY_FETCH=1`, 30 s timeout). A git failure never propagates out of `discover()`. (spec §4.3)
- The provider never runs `fetch`, `gc`, `prune`, `repair`, or any command that changes refs or a working tree. (spec §4.3)
- Only `git merge-tree` gets `GIT_OBJECT_DIRECTORY` (a temporary directory created for the scan) and `GIT_ALTERNATE_OBJECT_DIRECTORIES`; the directory is removed in a `finally` block when `discover()` returns. (spec §4.3)
- Integrated ⇔ the first line of `git merge-tree --write-tree <default> <HEAD sha>` equals `<default>^{tree}`. Fallback `merge-base --is-ancestor <HEAD> <default>` when git is below 2.38 or the repository is a partial clone (`remote.*.promisor` or `extensions.partialClone` set). (spec §4.4)
- Default branch: `symbolic-ref refs/remotes/origin/HEAD`, then `origin/main`, then `origin/master`. (spec §4.4)
- git below 2.36: no worktree entries; one diagnostic naming the installed version. (spec §4.4, §7)
- Per-worktree classification runs on a pool of 4 worker threads; HEAD commit times come from one `git log --no-walk=unsorted --format='%H %ct' <sha>…` per repository, chunked at 500 SHAs. (spec §4.2)
- States are checked in the order of spec §5.1, first match wins; label texts and advice messages are exactly those of spec §5.2.
- Reclaimable entries: `risk = Risk.RECLAIMABLE`, sized with `size_path_detailed`, `usage = DiskUsage(size, size)`, `actions = (CommandAction(("git", "-C", <repo>, "worktree", "remove", <path>)),)`, `recipe = [<that command, rendered>]`. Never `--force`. (spec §5.2)
- Advice entries: `risk = Risk.DANGEROUS`, `size_bytes = 0`, `usage = DiskUsage(None, None)`, `actions = (AdviceAction(<message>),)`. Never sized. (spec §5.2)
- `mtime` is the HEAD commit's committer time; `None` plus one diagnostic when the batched log fails; unverifiable directories use the directory's own mtime. (spec §5.2)
- Tests select entries by provider, path or label, never by list position. (spec §8)
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. PR descriptions end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

## Commands

Run everything from the repository root. These mirror CI (`.github/workflows/ci.yml`):

```bash
uv run --extra dev --extra web ruff check src tests
uv run --extra dev --extra web ruff format --check src tests
uv run --extra dev --extra web mypy
uv run --extra dev --extra web pytest
```

## Decisions where the spec is silent

Each was checked against real git while this plan's code was built and tested.

1. **Pointer parsing lives in `_git.py`** (`read_worktree_pointer`), so the project walk and the provider's broken-pointer advice read `.git` files the same way. A relative `gitdir:` resolves against the pointer's directory. Only a gitdir whose parent is named `worktrees` is a worktree; submodule pointers (`…/.git/modules/<name>`) are ignored.
2. **Bare records** produce no entry and no diagnostic. **Prunable or missing** worktrees produce no entry and one diagnostic per repository suggesting `git -C <repo> worktree prune`.
3. **A repository whose `worktree list` fails** reports none of its worktrees, including its unregistered folder children and pointers, beyond the one diagnostic (§7: "its worktrees are not reported").
4. **Unregistered directories** (§4.2 step 5): a broken pointer that no discovered repository lists is also unverifiable. For a child of `.claude/worktrees`, the label's repository is the project that contains `.claude`.
5. **`--git-common-dir` failure** falls back to `is-ancestor` for that repository, with one diagnostic. **Unreadable config** during the partial-clone check counts as a partial clone. Both only select the fallback, which never over-reports.
6. **An `origin/HEAD` target starting with `-`** is ignored, so it can never reach a later git call as an option.
7. **merge-tree exit codes:** exit 0 or 1 with a tree id on the first line is an answer (exit 1 is a conflict, so not integrated); anything else is a git error.
8. **An unborn HEAD** (the all-zero id) is left out of the log batch; its integration check fails and it becomes a git error.

## Fixture provenance

Behaviour the code relies on, observed with git 2.50.1 (Apple Git-155) in hermetic throwaway repositories:

- `symbolic-ref --quiet --short refs/remotes/origin/HEAD` prints `origin/main`; with no `origin/HEAD` it prints nothing and exits 1. `rev-parse --verify --quiet origin/master` exits 1 when the ref is absent.
- `merge-base --is-ancestor` exits 0 (ancestor), 1 (not an ancestor) or 128 (unknown object).
- `merge-tree --write-tree` exits 0 with the result tree on line 1; exits 1 with the tree on line 1 followed by conflict details; and exits 1 with no stdout for an unknown revision (`merge-tree: <rev> - not something we can merge`).
- Edits on adjacent lines conflict in merge-tree; edits separated by one unchanged line merge cleanly. The §4.4 row "squash merge after the default branch changed nearby lines" therefore uses a one-line gap, and a second, adjacent-line case documents the safe under-report.
- `log --no-walk=unsorted --format='%H %ct'` prints a repeated commit once; one unknown commit fails the whole call with exit 128 (`fatal: bad object`).
- A `--filter=blob:none` clone sets `remote.origin.promisor true`; `extensions.partialclone` stays unset.
- `.git` pointer files hold an absolute `gitdir:` by default; `worktree add --relative-paths` writes `gitdir: ../../clone/.git/worktrees/rel`; a bare repository's worktree points at `<repo.git>/worktrees/<name>`; a submodule points at `../.git/modules/<name>`.
- `rev-parse --path-format=absolute --git-common-dir` prints the same `<repo>/.git` from the primary and every linked worktree.
- After the repository is moved, `worktree list` in its new location still lists the worktree (not prunable), and `rev-parse --show-toplevel` inside the worktree fails.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/devdoctor/providers/_git.py` | modify | `WorktreePointer` and `read_worktree_pointer` |
| `src/devdoctor/providers/project_artifacts.py` | modify | the walk also records `GitCandidates`; `ProjectArtifactIndex.git_candidates()` |
| `tests/test_project_index_git_candidates.py` | create | candidate recording |
| `src/devdoctor/providers/_worktree_states.py` | create | state order, labels, advice messages (pure) |
| `tests/test_worktree_states.py` | create | table-driven classification and copy |
| `tests/git_fixture.py` | create | `GitFixture` and `Checkout`: hermetic real repositories |
| `tests/conftest.py` | modify | the `git_fixture` fixture |
| `src/devdoctor/providers/_git_queries.py` | create | read-only repository queries |
| `tests/test_git_queries.py` | create | query units on `FakeShell`, the §4.4 table on real git |
| `src/devdoctor/providers/git_worktrees.py` | create | `GitWorktreeProvider` |
| `tests/test_git_worktrees_provider.py` | create | every state, §7 failures, write-free and offline checks on real git |

---

### Task 1: The project index records git candidates

**Files:**
- Modify: `src/devdoctor/providers/_git.py` (imports; new block before `class StatusCounts`)
- Modify: `src/devdoctor/providers/project_artifacts.py` (imports, `ProjectArtifactIndex`, `_index_projects`, two helpers)
- Test: `tests/test_project_index_git_candidates.py`

**Interfaces:**
- Consumes: `_walk.DepthBudget`, the existing `_index_projects` walk.
- Produces:
  - `devdoctor.providers._git.WorktreePointer(path: Path, gitdir: Path, repository: Path, broken: bool)` (frozen dataclass)
  - `devdoctor.providers._git.read_worktree_pointer(directory: Path) -> WorktreePointer | None`
  - `devdoctor.providers.project_artifacts.GitCandidates(repositories: tuple[Path, ...], pointers: tuple[WorktreePointer, ...], folder_children: tuple[Path, ...])` (frozen dataclass)
  - `ProjectArtifactIndex.git_candidates() -> GitCandidates`, built by the same single walk as `candidates(query)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_project_index_git_candidates.py`:

```python
from pathlib import Path

from devdoctor.providers import project_artifacts
from devdoctor.providers._git import WorktreePointer
from devdoctor.providers.project_artifacts import GitCandidates, ProjectArtifactIndex


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pointer(directory: Path, gitdir: str) -> Path:
    _mkdir(directory)
    (directory / ".git").write_text(f"gitdir: {gitdir}\n")
    return directory


def _git_candidates(root: Path, monkeypatch) -> GitCandidates:
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    return ProjectArtifactIndex().git_candidates()


def test_records_repository_roots(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = _mkdir(root / "repo" / ".git").parent
    assert _git_candidates(root, monkeypatch).repositories == (repo,)


def test_records_a_worktree_pointer_and_derives_its_repository(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = root / "repo"
    admin = _mkdir(repo / ".git" / "worktrees" / "feature")
    worktree = _pointer(root / "wt" / "feature", str(admin))
    assert _git_candidates(root, monkeypatch).pointers == (
        WorktreePointer(path=worktree, gitdir=admin, repository=repo, broken=False),
    )


def test_resolves_a_relative_gitdir(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = root / "repo"
    admin = _mkdir(repo / ".git" / "worktrees" / "rel")
    worktree = _pointer(root / "wt" / "rel", "../../repo/.git/worktrees/rel")
    [pointer] = _git_candidates(root, monkeypatch).pointers
    assert pointer == WorktreePointer(path=worktree, gitdir=admin, repository=repo, broken=False)


def test_bare_repository_pointer_names_the_bare_directory(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    bare = root / "bare.git"
    admin = _mkdir(bare / "worktrees" / "from-bare")
    _pointer(root / "wt" / "from-bare", str(admin))
    [pointer] = _git_candidates(root, monkeypatch).pointers
    assert pointer.repository == bare
    assert pointer.broken is False


def test_pointer_to_a_missing_gitdir_is_broken(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    moved = tmp_path / "moved-away"
    _pointer(root / "wt" / "orphan", str(moved / ".git" / "worktrees" / "orphan"))
    [pointer] = _git_candidates(root, monkeypatch).pointers
    assert pointer.broken is True
    assert pointer.repository == moved


def test_ignores_submodule_and_malformed_git_files(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    _mkdir(root / "super" / ".git" / "modules" / "sub")
    _pointer(root / "super" / "sub", "../.git/modules/sub")
    odd = _mkdir(root / "odd")
    (odd / ".git").write_text("not a pointer\n")
    assert _git_candidates(root, monkeypatch).pointers == ()


def test_records_children_of_worktree_folders(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = root / "repo"
    _mkdir(repo / ".git")
    a = _mkdir(repo / ".worktrees" / "a")
    b = _mkdir(repo / ".worktrees" / "b")
    c = _mkdir(repo / ".claude" / "worktrees" / "c")
    _mkdir(repo / "docs" / "worktrees" / "not-a-worktree-folder")
    assert set(_git_candidates(root, monkeypatch).folder_children) == {a, b, c}


def test_git_candidates_and_artifact_queries_share_one_walk(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(tmp_path / "projects"))
    _mkdir(tmp_path / "projects" / "repo" / ".git")
    calls = []
    original = project_artifacts._index_projects

    def counting():
        calls.append(1)
        return original()

    monkeypatch.setattr(project_artifacts, "_index_projects", counting)
    index = ProjectArtifactIndex()
    index.git_candidates()
    index.candidates("node")
    assert len(calls) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_project_index_git_candidates.py -q`
Expected: collection error, `ImportError: cannot import name 'WorktreePointer' from 'devdoctor.providers._git'`.

- [ ] **Step 3: Add the pointer parser to `_git.py`**

Apply this change to `src/devdoctor/providers/_git.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/providers/_git.py b/src/devdoctor/providers/_git.py
--- a/src/devdoctor/providers/_git.py
+++ b/src/devdoctor/providers/_git.py
@@ -9,6 +9,7 @@ Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md

 from __future__ import annotations

+import os
 import re
 import subprocess
 from collections.abc import Mapping, Sequence
@@ -103,6 +104,50 @@ def _worktree_record(fields: dict[str, str]) -> WorktreeRecord | None:
     )


+@dataclass(frozen=True)
+class WorktreePointer:
+    """A directory whose ``.git`` is a file naming a linked worktree's git directory."""
+
+    path: Path
+    gitdir: Path
+    # The owning repository: ``<repo>`` for ``<repo>/.git/worktrees/<name>``, or the
+    # bare repository for ``<repo.git>/worktrees/<name>``. Derived from the path even
+    # when that path no longer exists.
+    repository: Path
+    # The gitdir does not exist, typically because the repository was moved.
+    broken: bool
+
+
+def read_worktree_pointer(directory: Path) -> WorktreePointer | None:
+    """Parse ``directory/.git`` when it is a file pointing at a linked worktree.
+
+    Submodules and other gitfiles are not worktrees and return None: only a gitdir
+    whose parent directory is named ``worktrees`` identifies a linked worktree. A
+    relative gitdir resolves against ``directory``.
+    """
+    dotgit = directory / ".git"
+    try:
+        if not dotgit.is_file() or dotgit.is_symlink():
+            return None
+        first_line = dotgit.read_text(encoding="utf-8", errors="replace").partition("\n")[0]
+    except OSError:
+        return None
+    raw = first_line.removeprefix("gitdir:").strip()
+    if raw == first_line.strip() or not raw:
+        return None
+    gitdir = Path(os.path.normpath(raw if os.path.isabs(raw) else directory / raw))
+    if gitdir.parent.name != "worktrees":
+        return None
+    admin = gitdir.parent.parent
+    repository = admin.parent if admin.name == ".git" else admin
+    return WorktreePointer(
+        path=directory,
+        gitdir=gitdir,
+        repository=repository,
+        broken=not gitdir.is_dir(),
+    )
+
+
 @dataclass(frozen=True)
 class StatusCounts:
     """Counts from ``git status --porcelain``.
```

- [ ] **Step 4: Record candidates in the project walk**

`.git` stays in `PRUNE_DIR_NAMES`: its presence is observed before pruning, and it is never descended into.

Apply this change to `src/devdoctor/providers/project_artifacts.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/providers/project_artifacts.py b/src/devdoctor/providers/project_artifacts.py
--- a/src/devdoctor/providers/project_artifacts.py
+++ b/src/devdoctor/providers/project_artifacts.py
@@ -4,9 +4,11 @@ import os
 import stat as stat_mod
 import threading
 from collections.abc import Iterable
+from dataclasses import dataclass
 from pathlib import Path

 from devdoctor.ports import Shell
+from devdoctor.providers._git import WorktreePointer, read_worktree_pointer
 from devdoctor.providers._walk import (
     PROJECT_MARKER_FILES,
     PROJECT_ROOTS,
@@ -68,23 +70,47 @@ def _roots() -> list[Path]:
     return roots


+@dataclass(frozen=True)
+class GitCandidates:
+    """Git locations the project walk observed, for the git worktree provider (spec §4.2)."""
+
+    repositories: tuple[Path, ...]
+    pointers: tuple[WorktreePointer, ...]
+    folder_children: tuple[Path, ...]
+
+
+@dataclass(frozen=True)
+class _ProjectIndex:
+    matches: dict[str, tuple[tuple[Path, Path], ...]]
+    git: GitCandidates
+
+
 class ProjectArtifactIndex:
     """One bounded filesystem index shared by all project providers in a scan."""

     def __init__(self) -> None:
         self._lock = threading.Lock()
-        self._matches: dict[str, tuple[tuple[Path, Path], ...]] | None = None
+        self._index: _ProjectIndex | None = None

     def candidates(self, query: str) -> tuple[tuple[Path, Path], ...]:
+        return self._built().matches[query]
+
+    def git_candidates(self) -> GitCandidates:
+        return self._built().git
+
+    def _built(self) -> _ProjectIndex:
         with self._lock:
-            if self._matches is None:
-                self._matches = _index_projects()
-            return self._matches[query]
+            if self._index is None:
+                self._index = _index_projects()
+            return self._index


-def _index_projects() -> dict[str, tuple[tuple[Path, Path], ...]]:
+def _index_projects() -> _ProjectIndex:
     matches: dict[str, list[tuple[Path, Path]]] = {query: [] for query in _PROJECT_QUERIES}
     seen_artifacts: set[tuple[int, int]] = set()
+    repositories: list[Path] = []
+    pointers: list[WorktreePointer] = []
+    folder_children: list[Path] = []
     for root in _roots():
         try:
             root_dev = root.lstat().st_dev
@@ -98,6 +124,17 @@ def _index_projects() -> dict[str, tuple[tuple[Path, Path], ...]]:
                 continue

             names = set(filenames)
+            # Observe git locations before pruning: `.git` itself is never descended into.
+            if ".git" in dirnames and _is_real_dir(project / ".git"):
+                repositories.append(project)
+            if ".git" in names:
+                pointer = read_worktree_pointer(project)
+                if pointer is not None:
+                    pointers.append(pointer)
+            if _is_worktree_folder(project):
+                folder_children.extend(
+                    project / name for name in sorted(dirnames) if _is_real_dir(project / name)
+                )
             for query, (marker_names, artifact_names) in _PROJECT_QUERIES.items():
                 if marker_names & names:
                     for artifact, key in _artifact_dirs(project, artifact_names):
@@ -111,7 +148,28 @@ def _index_projects() -> dict[str, tuple[tuple[Path, Path], ...]]:
                 if _walkable_child(project, name, _ALL_ARTIFACT_NAMES, root_dev)
             ]
             budget.descend(dirpath, dirnames, reset=bool(PROJECT_MARKER_FILES & names))
-    return {query: tuple(rows) for query, rows in matches.items()}
+    return _ProjectIndex(
+        matches={query: tuple(rows) for query, rows in matches.items()},
+        git=GitCandidates(
+            repositories=tuple(repositories),
+            pointers=tuple(pointers),
+            folder_children=tuple(folder_children),
+        ),
+    )
+
+
+def _is_real_dir(path: Path) -> bool:
+    try:
+        return stat_mod.S_ISDIR(path.lstat().st_mode)
+    except OSError:
+        return False
+
+
+def _is_worktree_folder(directory: Path) -> bool:
+    """``.worktrees``, or ``worktrees`` directly inside ``.claude`` (spec §4.2)."""
+    return directory.name == ".worktrees" or (
+        directory.name == "worktrees" and directory.parent.name == ".claude"
+    )


 def _artifact_dirs(
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_project_index_git_candidates.py tests/test_project_artifact_providers.py tests/test_git_plumbing.py -q`
Expected: `73 passed` (8 new, 8 existing project-artifact tests, 57 plumbing tests).

- [ ] **Step 6: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add src/devdoctor/providers/_git.py src/devdoctor/providers/project_artifacts.py tests/test_project_index_git_candidates.py
git commit -m "feat(git-worktrees): record git candidates in the project index" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Worktree states, labels and advice

**Files:**
- Create: `src/devdoctor/providers/_worktree_states.py`
- Test: `tests/test_worktree_states.py`

**Interfaces:**
- Consumes: `devdoctor.providers._git.StatusCounts(modified: int, untracked: int)` with `.is_clean`.
- Produces:
  - `WorktreeState` (`StrEnum`; each value is the label text): `INTEGRATED`, `DIRTY`, `NOT_INTEGRATED`, `BROKEN_POINTER`, `LOCKED`, `NO_DEFAULT_BRANCH`, `GIT_ERROR`, `UNVERIFIABLE`
  - `Integration` (`Enum`): `INTEGRATED`, `NOT_INTEGRATED`
  - `WorktreeFacts(toplevel_ok: bool, locked: bool, default_branch: str | None, failure: str | None = None, integration: Integration | None = None, status: StatusCounts | None = None)` (frozen)
  - `classify(facts: WorktreeFacts) -> WorktreeState | None` (`None` means more facts are needed)
  - `worktree_label(*, repository_name: str, directory: Path, state: WorktreeState, branch: str | None = None, head: str | None = None, detached: bool = False) -> str`
  - `advice_message(state, *, repository: Path, gitdir: Path | None = None, lock_reason: str | None = None, default_branch: str | None = None, failure: str | None = None, status: StatusCounts | None = None) -> str` (raises `ValueError` for `INTEGRATED`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_worktree_states.py`:

```python
from pathlib import Path

import pytest

from devdoctor.providers._git import StatusCounts
from devdoctor.providers._worktree_states import (
    Integration,
    WorktreeFacts,
    WorktreeState,
    advice_message,
    classify,
    worktree_label,
)

CLEAN = StatusCounts(modified=0, untracked=0)
DIRTY = StatusCounts(modified=7, untracked=3)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        pytest.param(
            WorktreeFacts(toplevel_ok=False, locked=True, default_branch=None),
            WorktreeState.BROKEN_POINTER,
            id="broken-pointer-wins-over-everything",
        ),
        pytest.param(
            WorktreeFacts(toplevel_ok=True, locked=True, default_branch=None),
            WorktreeState.LOCKED,
            id="locked-wins-over-no-default-branch",
        ),
        pytest.param(
            WorktreeFacts(toplevel_ok=True, locked=False, default_branch=None, failure="boom"),
            WorktreeState.NO_DEFAULT_BRANCH,
            id="no-default-branch-wins-over-git-error",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                failure="timed out after 30 s",
                integration=Integration.NOT_INTEGRATED,
            ),
            WorktreeState.GIT_ERROR,
            id="git-error-wins-over-not-integrated",
        ),
        pytest.param(
            WorktreeFacts(toplevel_ok=True, locked=False, default_branch="origin/main"),
            None,
            id="integration-still-needed",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.NOT_INTEGRATED,
                status=DIRTY,
            ),
            WorktreeState.NOT_INTEGRATED,
            id="not-integrated-ignores-status",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.INTEGRATED,
            ),
            None,
            id="status-still-needed",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.INTEGRATED,
                status=DIRTY,
            ),
            WorktreeState.DIRTY,
            id="integrated-but-dirty",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.INTEGRATED,
                status=CLEAN,
            ),
            WorktreeState.INTEGRATED,
            id="integrated-and-clean",
        ),
    ],
)
def test_classify_returns_the_first_matching_state(facts, expected):
    assert classify(facts) is expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        pytest.param(
            {"branch": "table-footers", "directory": Path("/r/.worktrees/table-footers")},
            "indexcat/table-footers · integrated",
            id="branch-matches-directory",
        ),
        pytest.param(
            {"branch": "fix/api-keys", "directory": Path("/r/wt/practical-feistel")},
            "indexcat/practical-feistel · fix/api-keys · integrated",
            id="branch-differs-from-directory",
        ),
        pytest.param(
            {"detached": True, "head": "e317178606aa", "directory": Path("/c/amj")},
            "indexcat/amj · detached @e317178 · integrated",
            id="detached-head",
        ),
    ],
)
def test_worktree_label(kwargs, expected):
    assert (
        worktree_label(repository_name="indexcat", state=WorktreeState.INTEGRATED, **kwargs)
        == expected
    )


def test_state_values_are_the_label_texts_from_the_spec():
    assert [state.value for state in WorktreeState] == [
        "integrated",
        "integrated, uncommitted changes",
        "not integrated",
        "broken pointer",
        "locked",
        "no default branch",
        "git error",
        "unverifiable",
    ]


REPO = Path("/p/indexcat")


@pytest.mark.parametrize(
    ("state", "kwargs", "expected"),
    [
        pytest.param(
            WorktreeState.BROKEN_POINTER,
            {"gitdir": Path("/old/indexcat/.git/worktrees/amj")},
            "This worktree's .git file points to /old/indexcat/.git/worktrees/amj, which does "
            'not exist; the repository was probably moved. Run "git -C /p/indexcat worktree '
            'repair", then rescan.',
            id="broken-pointer",
        ),
        pytest.param(
            WorktreeState.LOCKED,
            {"lock_reason": "agent running"},
            "Locked by git: agent running.",
            id="locked-with-reason",
        ),
        pytest.param(WorktreeState.LOCKED, {}, "Locked by git.", id="locked-without-reason"),
        pytest.param(
            WorktreeState.NO_DEFAULT_BRANCH,
            {},
            "Cannot determine the default branch of /p/indexcat: no origin/HEAD, origin/main "
            "or origin/master.",
            id="no-default-branch",
        ),
        pytest.param(
            WorktreeState.GIT_ERROR,
            {"failure": "timed out after 30 s"},
            "git failed while checking this worktree: timed out after 30 s.",
            id="git-error",
        ),
        pytest.param(
            WorktreeState.NOT_INTEGRATED,
            {"default_branch": "origin/main"},
            "Not integrated into origin/main. Anything inside it that other providers report "
            "can still be cleaned individually.",
            id="not-integrated",
        ),
        pytest.param(
            WorktreeState.DIRTY,
            {"default_branch": "origin/main", "status": DIRTY},
            "Integrated into origin/main, but has 7 modified and 3 untracked files. Commit, "
            "stash or discard them first.",
            id="integrated-dirty",
        ),
        pytest.param(
            WorktreeState.UNVERIFIABLE,
            {},
            "Inside a worktree folder, but not a registered git worktree. DevDoctor cannot "
            "verify what it contains.",
            id="unverifiable",
        ),
    ],
)
def test_advice_messages_match_the_spec(state, kwargs, expected):
    assert advice_message(state, repository=REPO, **kwargs) == expected


def test_integrated_has_no_advice():
    with pytest.raises(ValueError, match="not an advice state"):
        advice_message(WorktreeState.INTEGRATED, repository=REPO)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_worktree_states.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'devdoctor.providers._worktree_states'`.

- [ ] **Step 3: Implement the states module**

Create `src/devdoctor/providers/_worktree_states.py`:

```python
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
    the first git call among those later checks that failed.
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
        return WorktreeState.BROKEN_POINTER
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
    """The advice text for an advice-only state (spec §5.2)."""
    if state is WorktreeState.BROKEN_POINTER:
        message = (
            f"This worktree's .git file points to {gitdir}, which does not exist; the "
            f'repository was probably moved. Run "git -C {repository} worktree repair", '
            "then rescan."
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_worktree_states.py -q`
Expected: `22 passed`.

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add src/devdoctor/providers/_worktree_states.py tests/test_worktree_states.py
git commit -m "feat(git-worktrees): classify worktree states, labels and advice" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Real-git fixture and read-only repository queries

**Files:**
- Create: `tests/git_fixture.py`
- Modify: `tests/conftest.py` (imports; new `git_fixture` fixture before `FakeShell`)
- Create: `src/devdoctor/providers/_git_queries.py`
- Test: `tests/test_git_queries.py`

**Interfaces:**
- Consumes: `GitRunner.run(directory, args, *, extra_env=None) -> GitResult`, `GitRunner.version()`, `merge_tree_env`, `parse_worktree_porcelain`, `parse_status_porcelain`, `supports_merge_tree_write_tree` (all `_git.py`); `Integration` (Task 2).
- Produces (all in `devdoctor.providers._git_queries`):
  - `GitQueryError(Exception)`, one-line message; `GitQueryError.from_result(result)`
  - `DefaultBranch(name: str, tree: str)`, `MergeTreeContext(objects_dir: Path, common_git_dir: Path)` (frozen)
  - `list_worktrees(git, repository) -> list[WorktreeRecord]`
  - `resolve_default_branch(git, repository) -> DefaultBranch | None`
  - `is_partial_clone(git, repository) -> bool`
  - `common_git_dir(git, repository) -> Path`
  - `head_commit_times(git, repository, heads: Iterable[str]) -> dict[str, float]`
  - `check_integration(git, repository, *, default: DefaultBranch, head: str, merge_tree: MergeTreeContext | None) -> Integration`
  - `toplevel_matches(git, worktree) -> bool`
  - `worktree_status(git, worktree) -> StatusCounts`
  - Test support: the `git_fixture` fixture returning `tests.git_fixture.GitFixture`, whose `repository(path) -> Checkout` makes a repository with one commit on `main`; `Checkout` offers `git(*args)`, `commit(message, files)`, `rev(revision)`, `add_worktree(path, branch, *, start)`, `add_detached_worktree(path, *, start)`, `publish(branch)` and `object_counts()`.

- [ ] **Step 1: Add the real-git fixture**

Every git call in the fixture advances a shared clock by a minute. Commits replayed within the same second are byte-identical to the originals, which would silently turn the rebase scenarios into fast-forwards.

Create `tests/git_fixture.py`:

```python
"""Hermetic real-git repositories for tests (spec §8.3).

Request the ``git_fixture`` fixture from ``tests/conftest.py``: it isolates git from
the developer's configuration and from any enclosing repository first.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

# Every git call advances a shared clock by a minute, so no two commits share a
# timestamp. Commits replayed within the same second are byte-identical to the
# originals, which silently turns a rebase merge into a fast-forward.
_START_EPOCH = 1_700_000_000
_TICK_S = 60


class _Clock:
    def __init__(self) -> None:
        self.now = _START_EPOCH

    def tick(self) -> int:
        self.now += _TICK_S
        return self.now


class Checkout:
    """A working tree: a repository's primary worktree or one of its linked worktrees."""

    def __init__(self, path: Path, clock: _Clock) -> None:
        self.path = path
        self._clock = clock

    def git(self, *args: str) -> str:
        stamp = f"@{self._clock.tick()} +0000"
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed in {self.path}:\n{proc.stderr}")
        return proc.stdout.rstrip("\n")

    def commit(self, message: str, files: Mapping[str, str] | None = None) -> str:
        """Write ``files`` (relative path to content), commit everything, return the sha."""
        for name, content in (files or {}).items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.rev()

    def rev(self, revision: str = "HEAD") -> str:
        return self.git("rev-parse", "--verify", revision)

    def add_worktree(self, path: Path, branch: str, *, start: str = "main") -> Checkout:
        self.git("worktree", "add", "-q", "-b", branch, str(path), start)
        return Checkout(path, self._clock)

    def add_detached_worktree(self, path: Path, *, start: str = "main") -> Checkout:
        self.git("worktree", "add", "-q", "--detach", str(path), start)
        return Checkout(path, self._clock)

    def publish(self, branch: str = "main") -> None:
        """Point ``origin/<branch>`` and ``origin/HEAD`` at ``branch``, as a clone would."""
        self.git("update-ref", f"refs/remotes/origin/{branch}", branch)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")

    def object_counts(self) -> str:
        """``count-objects -v``: identical before and after anything write-free."""
        return self.git("count-objects", "-v")


class GitFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._clock = _Clock()

    def repository(self, path: Path) -> Checkout:
        """A new repository at ``path`` with one commit on ``main``."""
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-c", "init.defaultBranch=main", "init", "-q", str(path)],
            capture_output=True,
            check=True,
        )
        checkout = Checkout(path, self._clock)
        checkout.commit("Initial commit", {"README": "base\n"})
        return checkout
```

Apply this change to `tests/conftest.py` (for example with `git apply`):

```diff
diff --git a/tests/conftest.py b/tests/conftest.py
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -1,5 +1,6 @@
 from __future__ import annotations

+import os
 import threading
 from collections.abc import Mapping
 from dataclasses import dataclass, field
@@ -7,7 +8,9 @@ from pathlib import Path

 import pytest

+from devdoctor.providers._git import LOCAL_ENV_VARS
 from devdoctor.types import ShellResult
+from tests.git_fixture import GitFixture


 @pytest.fixture(autouse=True)
@@ -32,6 +35,21 @@ def _isolate_home_and_xdg_dirs(tmp_path: Path, monkeypatch):
     monkeypatch.setenv("HOME", str(tmp_path / "home"))


+@pytest.fixture
+def git_fixture(tmp_path: Path, monkeypatch) -> GitFixture:
+    """Real git, isolated from the developer's configuration and enclosing repositories."""
+    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
+    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
+    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
+    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
+        monkeypatch.setenv(name, "t")
+    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
+        monkeypatch.setenv(name, "t@t")
+    for name in LOCAL_ENV_VARS:
+        monkeypatch.delenv(name, raising=False)
+    return GitFixture(tmp_path)
+
+
 @dataclass
 class FakeShell:
     """Argv-keyed fake. Matches full argv tuple exactly.
```

- [ ] **Step 2: Write the failing tests**

The real-git table reproduces every row of spec §4.4, plus the adjacent-line conflict case.

Create `tests/test_git_queries.py`:

```python
import os
import shutil
from pathlib import Path

import pytest

from devdoctor.ports import RealShell
from devdoctor.providers._git import GitRunner, StatusCounts, supports_merge_tree_write_tree
from devdoctor.providers._git_queries import (
    HEAD_TIMES_CHUNK,
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
from devdoctor.providers._worktree_states import Integration
from devdoctor.types import ShellResult
from tests.conftest import FakeShell

REPO = Path("/r/app")
TREE = "a" * 40
OTHER_TREE = "b" * 40
HEAD = "c" * 40
SYMBOLIC_REF = ("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")


def _argv(directory: Path, *args: str) -> tuple[str, ...]:
    return ("git", "--no-optional-locks", "-C", str(directory), *args)


def _tree_of(name: str) -> tuple[str, ...]:
    return ("rev-parse", "--verify", "--quiet", f"{name}^{{tree}}")


def _ok(stdout: str = "") -> ShellResult:
    return ShellResult(0, stdout, "")


def _exit(code: int, stderr: str = "", stdout: str = "") -> ShellResult:
    return ShellResult(code, stdout, stderr)


def _git(responses: dict[tuple[str, ...], ShellResult]) -> tuple[GitRunner, FakeShell]:
    shell = FakeShell(responses=responses)
    return GitRunner(shell), shell


# --- default branch --------------------------------------------------------------


def test_default_branch_follows_origin_head():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _ok("origin/trunk\n"),
            _argv(REPO, *_tree_of("origin/trunk")): _ok(f"{TREE}\n"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/trunk", TREE)


def test_default_branch_falls_back_to_origin_main_then_origin_master():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _exit(1),
            _argv(REPO, *_tree_of("origin/main")): _exit(1),
            _argv(REPO, *_tree_of("origin/master")): _ok(f"{TREE}\n"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/master", TREE)


def test_dangling_origin_head_falls_through_to_origin_main():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _ok("origin/gone\n"),
            _argv(REPO, *_tree_of("origin/gone")): _exit(128, "fatal: bad revision"),
            _argv(REPO, *_tree_of("origin/main")): _ok(f"{TREE}\n"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/main", TREE)


def test_option_like_origin_head_is_never_passed_to_git():
    git, shell = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _ok("--output=x\n"),
            _argv(REPO, *_tree_of("origin/main")): _ok(f"{TREE}\n"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/main", TREE)
    assert all("--output=x" not in " ".join(call) for call in shell.calls[1:])


def test_no_default_branch_when_nothing_resolves():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _exit(1),
            _argv(REPO, *_tree_of("origin/main")): _exit(1),
            _argv(REPO, *_tree_of("origin/master")): _exit(1),
        }
    )
    assert resolve_default_branch(git, REPO) is None


# --- partial clone ---------------------------------------------------------------

PROMISOR_QUERY = (
    "config",
    "--get-regexp",
    r"^(remote\..*\.promisor|extensions\.partialclone)$",
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        pytest.param(_exit(1), False, id="no-keys"),
        pytest.param(_ok("remote.origin.promisor true\n"), True, id="promisor-remote"),
        pytest.param(_ok("remote.origin.promisor false\n"), False, id="promisor-false"),
        pytest.param(_ok("remote.origin.promisor\n"), True, id="bare-promisor-key"),
        pytest.param(_ok("extensions.partialclone origin\n"), True, id="extension"),
        pytest.param(_exit(3, "error: bad config line"), True, id="unreadable-config"),
    ],
)
def test_is_partial_clone(result, expected):
    git, _ = _git({_argv(REPO, *PROMISOR_QUERY): result})
    assert is_partial_clone(git, REPO) is expected


# --- integration -----------------------------------------------------------------

DEFAULT = DefaultBranch("origin/main", TREE)
CONTEXT = MergeTreeContext(Path("/tmp/objects"), Path("/r/app/.git"))
MERGE_TREE = ("merge-tree", "--write-tree", "origin/main", HEAD)
IS_ANCESTOR = ("merge-base", "--is-ancestor", HEAD, "origin/main")


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        pytest.param(_ok(f"{TREE}\n"), Integration.INTEGRATED, id="same-tree"),
        pytest.param(_ok(f"{OTHER_TREE}\n"), Integration.NOT_INTEGRATED, id="different-tree"),
        pytest.param(
            _exit(1, stdout=f"{OTHER_TREE}\n100644 {HEAD} 1\tdoc.txt\n"),
            Integration.NOT_INTEGRATED,
            id="conflict",
        ),
    ],
)
def test_merge_tree_integration(result, expected):
    git, shell = _git({_argv(REPO, *MERGE_TREE): result})
    assert check_integration(git, REPO, default=DEFAULT, head=HEAD, merge_tree=CONTEXT) is expected
    [env] = shell.envs
    assert env is not None
    assert env["GIT_OBJECT_DIRECTORY"] == "/tmp/objects"
    assert env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] == '"/r/app/.git/objects"'


def test_merge_tree_error_without_a_tree_raises_with_the_first_stderr_line():
    git, _ = _git(
        {_argv(REPO, *MERGE_TREE): _exit(1, "merge-tree: origin/main - not something we can merge")}
    )
    with pytest.raises(GitQueryError, match="not something we can merge"):
        check_integration(git, REPO, default=DEFAULT, head=HEAD, merge_tree=CONTEXT)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        pytest.param(_ok(), Integration.INTEGRATED, id="ancestor"),
        pytest.param(_exit(1), Integration.NOT_INTEGRATED, id="not-ancestor"),
    ],
)
def test_is_ancestor_fallback(result, expected):
    git, shell = _git({_argv(REPO, *IS_ANCESTOR): result})
    assert check_integration(git, REPO, default=DEFAULT, head=HEAD, merge_tree=None) is expected
    [env] = shell.envs
    assert env is not None
    assert env["GIT_OBJECT_DIRECTORY"] is None


def test_is_ancestor_error_raises():
    git, _ = _git({_argv(REPO, *IS_ANCESTOR): _exit(128, "fatal: Not a valid commit name")})
    with pytest.raises(GitQueryError, match="Not a valid commit name"):
        check_integration(git, REPO, default=DEFAULT, head=HEAD, merge_tree=None)


# --- HEAD commit times -----------------------------------------------------------


def _log(*commits: str) -> tuple[str, ...]:
    return _argv(REPO, "log", "--no-walk=unsorted", "--format=%H %ct", *commits, "--")


def test_head_commit_times_batches_unique_commits_and_skips_the_unborn_id():
    commits = [f"{n:040x}" for n in range(1, HEAD_TIMES_CHUNK + 2)]
    first, second = commits[:HEAD_TIMES_CHUNK], commits[HEAD_TIMES_CHUNK:]
    git, shell = _git(
        {
            _log(*first): _ok("".join(f"{c} 1700000000\n" for c in first)),
            _log(*second): _ok(f"{second[0]} 1700000060\n"),
        }
    )
    times = head_commit_times(git, REPO, [*commits, commits[0], "0" * 40])
    assert len(shell.calls) == 2
    assert times[commits[0]] == 1_700_000_000.0
    assert times[second[0]] == 1_700_000_060.0
    assert "0" * 40 not in times


def test_head_commit_times_without_commits_runs_nothing():
    git, shell = _git({})
    assert head_commit_times(git, REPO, ["0" * 40]) == {}
    assert shell.calls == []


def test_head_commit_times_failure_raises():
    git, _ = _git({_log(HEAD): _exit(128, f"fatal: bad object {HEAD}")})
    with pytest.raises(GitQueryError, match="bad object"):
        head_commit_times(git, REPO, [HEAD])


# --- listing, toplevel, status ---------------------------------------------------


def test_list_worktrees_parses_z_output():
    output = f"worktree /r/app\0HEAD {HEAD}\0branch refs/heads/main\0\0"
    git, _ = _git({_argv(REPO, "worktree", "list", "--porcelain", "-z"): _ok(output)})
    [record] = list_worktrees(git, REPO)
    assert (record.path, record.branch) == (Path("/r/app"), "main")


def test_list_worktrees_failure_raises():
    listing = _argv(REPO, "worktree", "list", "--porcelain", "-z")
    git, _ = _git({listing: _exit(128, "fatal: not a git repository")})
    with pytest.raises(GitQueryError, match="not a git repository"):
        list_worktrees(git, REPO)


def test_toplevel_matches_through_a_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    git, _ = _git({_argv(link, "rev-parse", "--show-toplevel"): _ok(f"{real}\n")})
    assert toplevel_matches(git, link) is True


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(_ok("/r/elsewhere\n"), id="different-toplevel"),
        pytest.param(_exit(128, "fatal: not a git repository"), id="git-fails"),
    ],
)
def test_toplevel_does_not_match(result):
    git, _ = _git({_argv(REPO, "rev-parse", "--show-toplevel"): result})
    assert toplevel_matches(git, REPO) is False


def test_worktree_status_counts_changes():
    status = _argv(REPO, "status", "--porcelain", "--untracked-files=normal")
    git, _ = _git({status: _ok(" M a.txt\n?? new.txt\n?? dir/\n")})
    assert worktree_status(git, REPO) == StatusCounts(modified=1, untracked=2)


def test_worktree_status_failure_raises():
    status = _argv(REPO, "status", "--porcelain", "--untracked-files=normal")
    git, _ = _git({status: _exit(128, "fatal: index file corrupt")})
    with pytest.raises(GitQueryError, match="index file corrupt"):
        worktree_status(git, REPO)


# --- real git --------------------------------------------------------------------

REAL_GIT = GitRunner(RealShell())
needs_merge_tree = pytest.mark.skipif(
    not supports_merge_tree_write_tree(REAL_GIT.version()),
    reason="git merge-tree --write-tree needs git 2.38",
)
DOC = "".join(f"line {n}\n" for n in range(1, 11))


def _edit(text: str, number: int, replacement: str) -> str:
    lines = text.splitlines(keepends=True)
    lines[number - 1] = f"{replacement}\n"
    return "".join(lines)


def _squash_two_commits(repo, worktree):
    worktree.commit("Feature, part 1", {"feature.txt": "one\n"})
    worktree.commit("Feature, part 2", {"feature.txt": "two\n"})
    repo.commit("Feature (squashed)", {"feature.txt": "two\n"})


def _squash_with_reviewer_edit(repo, worktree):
    worktree.commit("Feature", {"doc.txt": _edit(DOC, 2, "feature")})
    repo.commit(
        "Feature (squashed, reviewed)", {"doc.txt": _edit(_edit(DOC, 2, "feature"), 9, "review")}
    )


def _squash_after_nearby_change(repo, worktree):
    # One unchanged line separates the two edits, so the three-way merge is clean.
    worktree.commit("Feature", {"doc.txt": _edit(DOC, 5, "feature")})
    repo.commit("Other change", {"doc.txt": _edit(DOC, 3, "other")})
    repo.commit("Feature (squashed)", {"doc.txt": _edit(_edit(DOC, 3, "other"), 5, "feature")})


def _squash_after_adjacent_change(repo, worktree):
    # Edits on adjacent lines conflict, so merge-tree under-reports: never unsafe.
    worktree.commit("Feature", {"doc.txt": _edit(DOC, 5, "feature")})
    repo.commit("Other change", {"doc.txt": _edit(DOC, 4, "other")})
    repo.commit("Feature (squashed)", {"doc.txt": _edit(_edit(DOC, 4, "other"), 5, "feature")})


def _rebase_two_commits(repo, worktree):
    first = worktree.commit("Feature, part 1", {"a.txt": "a\n"})
    second = worktree.commit("Feature, part 2", {"b.txt": "b\n"})
    repo.commit("Unrelated", {"z.txt": "z\n"})
    repo.git("cherry-pick", first, second)


def _rebase_one_commit(repo, worktree):
    commit = worktree.commit("Feature", {"a.txt": "a\n"})
    repo.commit("Unrelated", {"z.txt": "z\n"})
    repo.git("cherry-pick", commit)


def _true_merge(repo, worktree):
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    repo.commit("Unrelated", {"z.txt": "z\n"})
    repo.git("merge", "--no-ff", "-q", "-m", "Merge feature", "feature")


def _squash_then_revert(repo, worktree):
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    repo.commit("Feature (squashed)", {"feature.txt": "feature\n"})
    repo.git("revert", "--no-edit", "HEAD")


def _not_merged(repo, worktree):
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    repo.commit("Unrelated", {"z.txt": "z\n"})


INTEGRATED = Integration.INTEGRATED
NOT_INTEGRATED = Integration.NOT_INTEGRATED


@needs_merge_tree
@pytest.mark.parametrize(
    ("build", "is_ancestor", "merge_tree"),
    [
        pytest.param(_squash_two_commits, NOT_INTEGRATED, INTEGRATED, id="squash-2-commits"),
        pytest.param(_squash_with_reviewer_edit, NOT_INTEGRATED, INTEGRATED, id="squash-reviewed"),
        pytest.param(_squash_after_nearby_change, NOT_INTEGRATED, INTEGRATED, id="squash-drift"),
        pytest.param(
            _squash_after_adjacent_change, NOT_INTEGRATED, NOT_INTEGRATED, id="squash-conflict"
        ),
        pytest.param(_rebase_two_commits, NOT_INTEGRATED, INTEGRATED, id="rebase-2-commits"),
        pytest.param(_rebase_one_commit, NOT_INTEGRATED, INTEGRATED, id="rebase-1-commit"),
        pytest.param(_true_merge, INTEGRATED, INTEGRATED, id="true-merge"),
        pytest.param(_squash_then_revert, NOT_INTEGRATED, NOT_INTEGRATED, id="squash-reverted"),
        pytest.param(_not_merged, NOT_INTEGRATED, NOT_INTEGRATED, id="not-merged"),
    ],
)
def test_integration_signals_match_the_spec_table(
    git_fixture, tmp_path, build, is_ancestor, merge_tree
):
    repo = git_fixture.repository(tmp_path / "app")
    repo.commit("Add doc", {"doc.txt": DOC})
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    build(repo, worktree)
    repo.publish()
    default = resolve_default_branch(REAL_GIT, repo.path)
    assert default is not None
    objects = tmp_path / "objects"
    objects.mkdir()
    context = MergeTreeContext(objects, common_git_dir(REAL_GIT, repo.path))
    before = repo.object_counts()

    head = worktree.rev()
    assert check_integration(REAL_GIT, repo.path, default=default, head=head, merge_tree=None) is (
        is_ancestor
    )
    assert (
        check_integration(REAL_GIT, repo.path, default=default, head=head, merge_tree=context)
        is merge_tree
    )
    assert repo.object_counts() == before


@pytest.mark.skipif(not os.environ.get("CI"), reason="only CI must provide git 2.38")
def test_ci_runs_the_merge_tree_path():
    assert supports_merge_tree_write_tree(REAL_GIT.version())


def test_real_default_branch_prefers_origin_head_then_origin_master(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    assert resolve_default_branch(REAL_GIT, repo.path) is None
    repo.git("update-ref", "refs/remotes/origin/master", "main")
    assert resolve_default_branch(REAL_GIT, repo.path) == DefaultBranch(
        "origin/master", repo.rev("main^{tree}")
    )
    repo.publish()
    assert resolve_default_branch(REAL_GIT, repo.path) == DefaultBranch(
        "origin/main", repo.rev("main^{tree}")
    )


def test_real_partial_clone_detection(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    assert is_partial_clone(REAL_GIT, repo.path) is False
    repo.git("config", "remote.origin.promisor", "true")
    assert is_partial_clone(REAL_GIT, repo.path) is True


def test_real_common_git_dir_is_shared_by_linked_worktrees(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    expected = Path(os.path.realpath(repo.path / ".git"))
    assert Path(os.path.realpath(common_git_dir(REAL_GIT, worktree.path))) == expected
    assert Path(os.path.realpath(common_git_dir(REAL_GIT, repo.path))) == expected


def test_real_head_commit_times_are_committer_times(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    head = worktree.commit("Feature", {"feature.txt": "feature\n"})
    expected = float(repo.git("log", "-1", "--format=%ct", head))
    assert head_commit_times(REAL_GIT, repo.path, [head, repo.rev()])[head] == expected
    with pytest.raises(GitQueryError):
        head_commit_times(REAL_GIT, repo.path, [head, "d" * 40])


def test_real_toplevel_breaks_when_the_repository_moves(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    assert toplevel_matches(REAL_GIT, worktree.path) is True
    shutil.move(repo.path, tmp_path / "moved")
    assert toplevel_matches(REAL_GIT, worktree.path) is False


def test_real_worktree_status(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    assert worktree_status(REAL_GIT, worktree.path).is_clean
    (worktree.path / "README").write_text("changed\n")
    (worktree.path / "new.txt").write_text("new\n")
    assert worktree_status(REAL_GIT, worktree.path) == StatusCounts(modified=1, untracked=1)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_git_queries.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'devdoctor.providers._git_queries'`.

- [ ] **Step 4: Implement the queries**

Create `src/devdoctor/providers/_git_queries.py`:

```python
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

# Tried in order after origin/HEAD (spec §4.4).
DEFAULT_BRANCH_FALLBACKS: tuple[str, ...] = ("origin/main", "origin/master")

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
    name: str  # a revision such as "origin/main"
    tree: str  # the tree of the commit it names


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

    A candidate counts only if it resolves to a tree, so a dangling ``origin/HEAD``
    falls through to the next candidate.
    """
    candidates: list[str] = []
    symbolic = git.run(
        repository, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]
    )
    target = symbolic.stdout.strip()
    # A name starting with "-" would be read as an option by later calls.
    if symbolic.ok and target and not target.startswith("-"):
        candidates.append(target)
    candidates.extend(name for name in DEFAULT_BRANCH_FALLBACKS if name not in candidates)
    for name in candidates:
        result = git.run(repository, ["rev-parse", "--verify", "--quiet", f"{name}^{{tree}}"])
        tree = result.stdout.strip()
        if result.ok and _OID_RE.fullmatch(tree):
            return DefaultBranch(name=name, tree=tree)
    return None


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
        result = git.run(repository, ["merge-base", "--is-ancestor", head, default.name])
        if result.returncode == 0:
            return Integration.INTEGRATED
        if result.returncode == 1:
            return Integration.NOT_INTEGRATED
        raise GitQueryError.from_result(result)
    result = git.run(
        repository,
        ["merge-tree", "--write-tree", default.name, head],
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_git_queries.py -q -rs`
Expected: `43 passed, 1 skipped`. The skip is `test_ci_runs_the_merge_tree_path`, which runs only when `CI` is set. On git below 2.38 the nine table cases also skip; CI must not.

- [ ] **Step 6: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add tests/git_fixture.py tests/conftest.py src/devdoctor/providers/_git_queries.py tests/test_git_queries.py
git commit -m "feat(git-worktrees): read-only repository queries and a real-git fixture" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `GitWorktreeProvider`

**Files:**
- Create: `src/devdoctor/providers/git_worktrees.py`
- Test: `tests/test_git_worktrees_provider.py`

**Interfaces:**
- Consumes: `ProjectArtifactIndex.git_candidates()` and `read_worktree_pointer` (Task 1); `WorktreeFacts`, `WorktreeState`, `classify`, `worktree_label`, `advice_message` (Task 2); every query in `_git_queries` (Task 3); `GitRunner`, `supports_worktree_list_z`, `supports_merge_tree_write_tree` (`_git.py`); `Provider`, `_stat_kwargs` (`base.py`); `size_path_detailed` (`sizer.py`); `AdviceAction`, `CommandAction`, `DiskUsage`, `Entry`, `Risk`, `render_cleanup_action` (`types.py`).
- Produces: `GitWorktreeProvider(shell: Shell, *, index: ProjectArtifactIndex | None = None)` with `discover() -> list[Entry]` and `diagnostics: list[str]`; module constant `WORKER_THREADS = 4`. PR 3 registers it with `index=project_index`, like the other index-backed providers in `registry.py`.

- [ ] **Step 1: Write the failing tests**

`RecordingShell` wraps `RealShell`, records every call's argv and environment, and can intercept calls to inject a timeout or a failure while the rest run against real git.

Create `tests/test_git_worktrees_provider.py`:

```python
import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from devdoctor.ports import RealShell
from devdoctor.providers import git_worktrees
from devdoctor.providers._git import GitRunner, supports_merge_tree_write_tree
from devdoctor.providers.git_worktrees import GitWorktreeProvider
from devdoctor.types import AdviceAction, CommandAction, DiskUsage, Risk, ShellResult
from tests.conftest import FakeShell

needs_merge_tree = pytest.mark.skipif(
    not supports_merge_tree_write_tree(GitRunner(RealShell()).version()),
    reason="git merge-tree --write-tree needs git 2.38",
)


class RecordingShell:
    """RealShell that records every call and lets a test intercept some of them."""

    def __init__(self, intercept=None):
        self._real = RealShell()
        self._intercept = intercept
        self._lock = threading.Lock()
        self.calls: list[tuple[tuple[str, ...], dict[str, str | None] | None]] = []

    def run(self, argv, *, check=False, timeout=None, env=None):
        with self._lock:
            self.calls.append((tuple(argv), None if env is None else dict(env)))
        if self._intercept is not None:
            result = self._intercept(tuple(argv))
            if result is not None:
                return result
        return self._real.run(argv, check=check, timeout=timeout, env=env)

    def which(self, binary):
        return self._real.which(binary)


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects"  # DEVDOCTOR_PROJECT_ROOTS, pinned by tests/conftest.py
    root.mkdir()
    return root


@pytest.fixture
def app(git_fixture, projects):
    return git_fixture.repository(projects / "app")


def _merge(repo, worktree, branch="feature"):
    """Commit on the worktree's branch and merge it into main: integrated on any git."""
    head = worktree.commit("Feature", {f"{branch}.txt": "feature\n"})
    repo.git("merge", "--no-ff", "-q", "-m", f"Merge {branch}", branch)
    return head


def _discover(shell=None):
    provider = GitWorktreeProvider(shell or RealShell())
    return provider.discover(), provider


def _entry(entries, path):
    matches = [e for e in entries if os.path.realpath(e.path) == os.path.realpath(path)]
    assert len(matches) == 1, [e.label for e in entries]
    return matches[0]


def _advice(entry):
    [action] = entry.actions
    assert isinstance(action, AdviceAction)
    return action.message


def _assert_advice_shape(entry):
    assert entry.risk is Risk.DANGEROUS
    assert entry.size_bytes == 0
    assert entry.usage == DiskUsage(None, None)
    assert entry.recipe == []


def test_integrated_clean_worktree_is_reclaimable(app, projects):
    worktree = app.add_worktree(projects / "app" / ".worktrees" / "feature", "feature")
    head = _merge(app, worktree)
    app.publish()

    entries, _ = _discover()

    entry = _entry(entries, worktree.path)
    command = ("git", "-C", str(app.path), "worktree", "remove", str(worktree.path))
    assert entry.provider == "git-worktrees"
    assert entry.id == str(worktree.path)
    assert entry.label == "app/feature · integrated"
    assert entry.risk is Risk.RECLAIMABLE
    assert entry.actions == (CommandAction(command),)
    assert entry.recipe == [shlex.join(command)]
    assert entry.size_bytes > 0
    assert entry.usage == DiskUsage(entry.size_bytes, entry.size_bytes)
    assert entry.mtime == float(app.git("log", "-1", "--format=%ct", head))


def test_primary_worktree_has_no_entry(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    entries, provider = _discover()
    assert [e.path for e in entries] == [worktree.path]
    assert provider.diagnostics == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        pytest.param({"README": "changed\n"}, "1 modified and 0 untracked", id="modified"),
        pytest.param({"new.txt": "new\n"}, "0 modified and 1 untracked", id="untracked"),
    ],
)
def test_integrated_worktree_with_changes_is_advice(app, projects, change, expected):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    for name, content in change.items():
        (worktree.path / name).write_text(content)

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "app/feature · integrated, uncommitted changes"
    _assert_advice_shape(entry)
    assert _advice(entry) == (
        f"Integrated into origin/main, but has {expected} files. "
        "Commit, stash or discard them first."
    )


def test_not_integrated_worktree_is_advice(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    worktree.commit("Unmerged work", {"work.txt": "work\n"})
    app.publish()

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "app/feature · not integrated"
    _assert_advice_shape(entry)
    assert _advice(entry).startswith("Not integrated into origin/main.")


def test_locked_worktree_is_advice_with_the_reason(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    app.git("worktree", "lock", "--reason", "agent running", str(worktree.path))

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "app/feature · locked"
    assert _advice(entry) == "Locked by git: agent running."


def test_repository_without_a_default_branch_gives_advice(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)  # never published: no origin/HEAD, origin/main or origin/master

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "app/feature · no default branch"
    assert _advice(entry) == (
        f"Cannot determine the default branch of {app.path}: no origin/HEAD, origin/main "
        "or origin/master."
    )


def test_moved_repository_leaves_a_broken_pointer(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    moved = projects / "moved-app"
    shutil.move(app.path, moved)

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "moved-app/feature · broken pointer"
    _assert_advice_shape(entry)
    assert _advice(entry) == (
        f"This worktree's .git file points to {app.path / '.git' / 'worktrees' / 'feature'}, "
        "which does not exist; the repository was probably moved. Run "
        f'"git -C {moved} worktree repair", then rescan.'
    )


def test_detached_worktree_label_names_the_commit(app, projects):
    worktree = app.add_detached_worktree(projects / "wt" / "review")
    app.publish()

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == f"app/review · detached @{worktree.rev()[:7]} · integrated"
    assert entry.risk is Risk.RECLAIMABLE


def test_branch_differing_from_the_directory_is_in_the_label(app, projects):
    worktree = app.add_worktree(projects / "wt" / "practical-feistel", "fix/api-keys")
    _merge(app, worktree, branch="fix/api-keys")
    app.publish()
    entry = _entry(_discover()[0], worktree.path)
    assert entry.label == "app/practical-feistel · fix/api-keys · integrated"


def test_worktree_outside_every_root_is_found_through_its_repository(app, tmp_path):
    worktree = app.add_worktree(tmp_path / "elsewhere" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    assert _entry(_discover()[0], worktree.path).risk is Risk.RECLAIMABLE


def test_repository_outside_every_root_is_found_through_a_worktree(git_fixture, tmp_path, projects):
    repo = git_fixture.repository(tmp_path / "elsewhere" / "app")
    worktree = repo.add_worktree(projects / "wt" / "feature", "feature")
    _merge(repo, worktree)
    repo.publish()

    entry = _entry(_discover()[0], worktree.path)

    command = ("git", "-C", str(repo.path), "worktree", "remove", str(worktree.path))
    assert entry.actions == (CommandAction(command),)


def test_unregistered_worktree_folder_child_is_unverifiable(app, projects):
    scratch = projects / "app" / ".worktrees" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "notes.txt").write_text("notes\n")
    agent = projects / "app" / ".claude" / "worktrees" / "agent"
    agent.mkdir(parents=True)

    entries = _discover()[0]

    entry = _entry(entries, scratch)
    assert entry.label == "app/scratch · unverifiable"
    _assert_advice_shape(entry)
    assert entry.mtime == scratch.lstat().st_mtime
    assert _advice(entry) == (
        "Inside a worktree folder, but not a registered git worktree. DevDoctor cannot "
        "verify what it contains."
    )
    assert _entry(entries, agent).label == "app/agent · unverifiable"


def test_missing_worktree_has_no_entry_and_suggests_prune(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    shutil.rmtree(worktree.path)

    entries, provider = _discover()

    assert entries == []
    assert provider.diagnostics == [
        f"git-worktrees: 1 registered worktree(s) of {app.path} no longer exist; "
        f'run "git -C {app.path} worktree prune"'
    ]


def test_timeout_gives_one_worktree_git_error_advice_and_the_others_classify(app, projects):
    slow = app.add_worktree(projects / "wt" / "slow", "slow")
    fast = app.add_worktree(projects / "wt" / "fast", "fast")
    slow_head = _merge(app, slow, branch="slow")
    _merge(app, fast, branch="fast")
    app.publish()

    def intercept(argv):
        if slow_head in argv and {"merge-tree", "merge-base"} & set(argv):
            raise subprocess.TimeoutExpired(list(argv), 30)

    entries, _ = _discover(RecordingShell(intercept))

    slow_entry = _entry(entries, slow.path)
    assert slow_entry.label == "app/slow · git error"
    assert _advice(slow_entry) == "git failed while checking this worktree: timed out after 30 s."
    assert _entry(entries, fast.path).risk is Risk.RECLAIMABLE


@needs_merge_tree
def test_discover_writes_no_objects_and_removes_its_temporary_directory(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    app.commit("Feature (squashed)", {"feature.txt": "feature\n"})
    app.publish()
    before = app.object_counts()
    shell = RecordingShell()

    entries, _ = _discover(shell)

    assert _entry(entries, worktree.path).risk is Risk.RECLAIMABLE  # merge-tree ran
    assert app.object_counts() == before
    object_dirs = {
        env["GIT_OBJECT_DIRECTORY"]
        for _, env in shell.calls
        if env and env.get("GIT_OBJECT_DIRECTORY")
    }
    assert len(object_dirs) == 1
    assert not Path(object_dirs.pop()).exists()


def test_every_git_call_is_offline(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    shell = RecordingShell()

    _discover(shell)

    assert shell.calls
    for argv, env in shell.calls:
        assert argv[:2] == ("git", "--no-optional-locks")
        assert env is not None
        assert env["GIT_NO_LAZY_FETCH"] == "1"
        assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_inherited_repository_variables_do_not_redirect_checks(
    git_fixture, app, projects, tmp_path, monkeypatch
):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    other = git_fixture.repository(tmp_path / "other")
    (other.path / "dirty.txt").write_text("dirty\n")
    monkeypatch.setenv("GIT_DIR", str(other.path / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other.path))

    assert _entry(_discover()[0], worktree.path).risk is Risk.RECLAIMABLE


def _squash_merged(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    app.commit("Feature (squashed)", {"feature.txt": "feature\n"})
    app.publish()
    return worktree


def _uses_merge_tree(shell):
    return any("merge-tree" in argv for argv, _ in shell.calls)


def test_partial_clone_falls_back_to_is_ancestor(app, projects):
    worktree = _squash_merged(app, projects)
    app.git("config", "remote.origin.promisor", "true")
    shell = RecordingShell()

    entry = _entry(_discover(shell)[0], worktree.path)

    assert entry.label == "app/feature · not integrated"  # a squash merge is invisible
    assert not _uses_merge_tree(shell)


def test_git_before_2_38_falls_back_to_is_ancestor(app, projects):
    worktree = _squash_merged(app, projects)

    def old_git(argv):
        return ShellResult(0, "git version 2.37.0\n", "") if argv[-1] == "version" else None

    shell = RecordingShell(old_git)
    entry = _entry(_discover(shell)[0], worktree.path)

    assert entry.label == "app/feature · not integrated"
    assert not _uses_merge_tree(shell)


def test_git_before_2_36_reports_nothing():
    version = ("git", "--no-optional-locks", "-C", "/", "version")
    shell = FakeShell(responses={version: ShellResult(0, "git version 2.35.8\n", "")})
    entries, provider = _discover(shell)
    assert entries == []
    assert provider.diagnostics == [
        "git-worktrees: worktree listing needs git 2.36 and git 2.35.8 could not be "
        "confirmed to support it; no worktrees reported"
    ]


def test_temporary_directory_failure_falls_back_to_is_ancestor(app, projects, monkeypatch):
    worktree = _squash_merged(app, projects)

    def refuse(**kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(git_worktrees.tempfile, "mkdtemp", refuse)
    shell = RecordingShell()

    entries, provider = _discover(shell)

    assert _entry(entries, worktree.path).label == "app/feature · not integrated"
    assert not _uses_merge_tree(shell)
    assert provider.diagnostics == [
        "git-worktrees: could not create a temporary object directory (no space left on "
        "device); checking integration with merge-base --is-ancestor"
    ]


@needs_merge_tree
def test_temporary_directory_removal_failure_is_a_diagnostic(app, projects, monkeypatch):
    _squash_merged(app, projects)
    created = []
    real_mkdtemp = git_worktrees.tempfile.mkdtemp
    real_rmtree = git_worktrees.shutil.rmtree

    def mkdtemp(**kwargs):
        created.append(real_mkdtemp(**kwargs))
        return created[-1]

    def refuse(path):
        raise OSError("busy")

    monkeypatch.setattr(git_worktrees.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(git_worktrees.shutil, "rmtree", refuse)

    _, provider = _discover()

    assert provider.diagnostics == [
        f"git-worktrees: could not remove temporary object directory {created[0]}: busy"
    ]
    real_rmtree(created[0])


def test_failed_worktree_listing_reports_nothing_for_that_repository(app, projects):
    worktree = app.add_worktree(projects / "app" / ".worktrees" / "feature", "feature")
    (projects / "app" / ".worktrees" / "scratch").mkdir()
    app.publish()

    def fail_listing(argv):
        if "list" in argv and "worktree" in argv:
            return ShellResult(128, "", "fatal: bad config line 1\n")
        return None

    entries, provider = _discover(RecordingShell(fail_listing))

    assert entries == []
    assert provider.diagnostics == [
        f"git-worktrees: git worktree list failed for {app.path}: fatal: bad config line 1"
    ]
    assert worktree.path.exists()


def test_failed_head_times_leave_mtime_unknown(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()

    def fail_log(argv):
        return ShellResult(128, "", "fatal: bad object\n") if "log" in argv else None

    entries, provider = _discover(RecordingShell(fail_log))

    assert _entry(entries, worktree.path).mtime is None
    assert provider.diagnostics == [
        f"git-worktrees: could not read HEAD commit times for {app.path}: fatal: bad object"
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_git_worktrees_provider.py -q`
Expected: collection error, `ImportError: cannot import name 'git_worktrees' from 'devdoctor.providers'`.

- [ ] **Step 3: Implement the provider**

Create `src/devdoctor/providers/git_worktrees.py`:

```python
"""Linked git worktrees, reclaimable once integrated into the default branch and clean.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
"""

from __future__ import annotations

import os
import shutil
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
            if record.prunable or not record.path.is_dir():
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_git_worktrees_provider.py -q`
Expected: `25 passed`. On git below 2.38, the two `needs_merge_tree` tests skip.

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev --extra web pytest -q -rs`
Expected: no failures. From `a9d80d8` (417 passed) the count grows by 98: `515 passed, 1 skipped`.

- [ ] **Step 6: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add src/devdoctor/providers/git_worktrees.py tests/test_git_worktrees_provider.py
git commit -m "feat(git-worktrees): discover and classify linked worktrees" -m "Not registered yet: containment and registration ship together in PR 3." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Verify the PR and open it

**Files:** none.

- [ ] **Step 1: Confirm the provider is not registered**

```bash
git diff main --stat -- src/devdoctor/registry.py CHANGELOG.md
grep -rl "GitWorktreeProvider" src
```

Expected: no diff output, and `grep` lists only `src/devdoctor/providers/git_worktrees.py`.

- [ ] **Step 2: Run the full CI mirror**

Run each command from the Commands section.
Expected: ruff `All checks passed!`; ruff format `already formatted`; mypy `Success: no issues found`; pytest with no failures.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/git-worktree-discovery
gh pr create --base main --title "feat: git worktree discovery and classification (unregistered)" --body "$(cat <<'EOF'
PR 2 of 4 for #79, per the design spec (docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §9). No user-visible behaviour change: the provider is not registered.

## What

- The shared project walk also records git candidates: repository roots, `.git` worktree pointers (relative gitdirs resolved, submodules ignored, broken ones flagged) and children of `.worktrees` and `.claude/worktrees`.
- `_worktree_states.py`: the §5.1 state order, labels and advice text, as pure functions.
- `_git_queries.py`: read-only queries on `GitRunner`: worktree listing, default branch, partial clone, common dir, batched HEAD times, integration (merge-tree into a temporary object directory, or `is-ancestor`), toplevel and status.
- `GitWorktreeProvider`: one listing per repository, per-repository facts, 4 worker threads, sizing only for reclaimable worktrees, `git worktree remove` without `--force`, and the §7 diagnostics.

## Tests

- Real-git fixture (`tests/git_fixture.py`), hermetic from the developer's git config.
- Every §4.4 row on real git, for both merge-tree and `is-ancestor`.
- Every §5.1 state, plus a timeout on one worktree, write-free (`count-objects` unchanged, temporary directory gone), offline guards on every call, inherited `GIT_DIR`/`GIT_WORK_TREE`, and the partial-clone, old-git and temporary-directory fallbacks.

## Not in this PR

Containment, the zero-byte filter exemption, web cleanup changes, registration and the CHANGELOG ship together in PR 3.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge once the required checks pass**

The required checks are `Python (lint, types, tests)` and `Web (typecheck, tests, build)`. When both pass:

```bash
gh pr merge --squash --delete-branch
```

If a check fails, read its log, fix the cause on the branch, and push again. Do not merge on a red check.
