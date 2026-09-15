# Re-verify Git Worktrees Before Removal (#110) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cleanup re-classifies every git worktree immediately before `git worktree remove`, so a worktree that changed after the scan (for example a new commit on a detached HEAD) is skipped instead of removed.

**Architecture:** `GitWorktreeProvider.verify_removable(entry)` re-runs the provider's full classification on one worktree against current state and answers `None` or a reason, never raising. The pure cleanup state machine yields a new `VerifyRequired(entry)` event immediately before each approved reclaimable worktree's removal; the CLI adapter, the async adapter and the web `CleanupRunner` answer it (the async ones via `asyncio.to_thread`), and refuse when given no verifier. `devdoctor clean` and `POST /api/clean/jobs` pass the provider's verifier.

**Tech Stack:** Python 3.12, pytest (+ pytest-asyncio, `asyncio_mode = "auto"`), real git, Click, FastAPI/httpx; ruff, mypy (strict), uv.

**Spec:** `docs/superpowers/specs/2026-09-15-worktree-cleanup-reverify-design.md` (approved; merged in #112), which amends `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md`. Base `b14d65b`.

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100`, rules `E, F, I, UP, B, SIM, PL, RUF`; `mypy --strict` over `src/devdoctor`.
- Removal proceeds only if the worktree is still **integrated, clean** (provider state `WorktreeState.INTEGRATED`) at the moment of verification. A moved HEAD is re-classified, not blocked. (spec §2.1–2.2)
- `VerifyRequired(entry)` is yielded only for approved entries where `is_reclaimable_worktree(entry)` is true, immediately before that entry's actions; never for declined or skipped selections, advice entries, other providers' entries, or preview runs. (spec §3.1)
- A refusal resolves as `CleanResult(entry_id=entry.id, status="skipped", freed_bytes=0, message=f"changed since the scan: {reason}; rescan before cleaning")`, yields no `ExecuteStep`, and is not recorded as removed, so approved entries inside it run normally. (spec §3.1)
- Every adapter answers `VerifyRequired`; with no verifier the answer is `"cannot verify worktree removal"`. The async adapters run the verifier with `asyncio.to_thread`. (spec §3.2)
- `verify_removable` answers: `"could not verify: unexpected cleanup action"`; `"cannot verify: git version unknown"`; `"cannot verify: git <x.y.z> is older than 2.36"`; `"git error: <failure summary>"` when `worktree list` fails; `"no longer registered"`; the state label for any non-integrated state; `"could not verify: <exc>"` for any exception. It never raises. (spec §3.3, §4)
- Verification follows the git invocation contract: write-free, offline, merge-tree writes only to a temporary object directory removed in a `finally`. (spec §3.3; provider spec §4.3)
- The recipe script is unchanged. (spec §2.4)
- Tests select entries by provider, path, id or label, never by list position.
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

1. **Task order keeps `main` green at every commit.** The provider's verifier lands first (Task 1). The event, the adapters and the CLI/web wiring land together (Task 2): adapters refuse when given no verifier, so shipping them before the wiring would make `devdoctor clean` skip every worktree.
2. **`verify_removable` reuses the scan's code paths** — `_linked_worktrees` (states 1 and 2), `_repository_facts` (called with no linked records, so no `git log`), `_create_objects_dir`/`_remove_objects_dir`, and `_classify` — so verification can never disagree with a scan about what "integrated, clean" means.
3. **The removal target is parsed with structural pattern matching** on the entry's single `CommandAction`: `("git", "-C", <repo>, "worktree", "remove", <path>)` with `<path> == str(entry.path)`.
4. **`cleanup.answer_verify(verify, entry)`** is the one async helper both `run_async` and `CleanupRunner` use, so the `to_thread` call and the no-verifier refusal live in one place.
5. **The existing e2e test that relied on git refusing a dirty worktree** now passes a verifier, so the refusal comes from verification: status `skipped`, message `changed since the scan: integrated, uncommitted changes; rescan before cleaning`.
6. **The CLI e2e test simulates the race without sleeps** by replacing `real_prompts` so the per-entry prompt commits in the worktree before answering `y`; it wraps `cleanup_run` to capture results because the CLI prints only totals.

## File Structure

| File | Task | Change | Responsibility |
|---|---|---|---|
| `src/devdoctor/providers/git_worktrees.py` | 1 | modify | `verify_removable`, `_verify_removable`, `_removal_target` |
| `tests/test_git_worktrees_provider.py` | 1 | modify | real-git verification tests |
| `src/devdoctor/cleanup.py` | 2 | modify | `VerifyRequired`, `Verify`, `NO_VERIFIER_REASON`, `answer_verify`, executor step, `run`/`run_async` `verify=` |
| `src/devdoctor/web/cleanup_runner.py` | 2 | modify | `verify` field; answers `VerifyRequired` |
| `src/devdoctor/cli.py` | 2 | modify | `clean` passes the provider's verifier |
| `src/devdoctor/web/routes_clean.py` | 2 | modify | `start_job` passes the provider's verifier |
| `tests/test_cleanup_core.py` | 2 | modify | state-machine and adapter tests |
| `tests/web/test_cleanup_runner.py` | 2 | modify | runner refusal test |
| `tests/test_worktree_containment_e2e.py` | 2 | modify | CLI and web race tests; updated refusal test |
| provider spec, `README.md`, `CHANGELOG.md` | 2 | modify | documentation of the re-check |

---

### Task 1: `GitWorktreeProvider.verify_removable`

**Files:**
- Modify: `src/devdoctor/providers/git_worktrees.py`
- Test: `tests/test_git_worktrees_provider.py`

**Interfaces:**
- Consumes (existing): `GitRunner.version()`, `supports_worktree_list_z`, `supports_merge_tree_write_tree`, `list_worktrees`, `GitQueryError`, `WorktreeState`, and the provider's `_linked_worktrees`, `_repository_facts`, `_classify`, `_create_objects_dir`, `_remove_objects_dir`, `_real`.
- Produces: `GitWorktreeProvider.verify_removable(self, entry: Entry) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Apply this change to `tests/test_git_worktrees_provider.py` (for example with `git apply`):

```diff
diff --git a/tests/test_git_worktrees_provider.py b/tests/test_git_worktrees_provider.py
--- a/tests/test_git_worktrees_provider.py
+++ b/tests/test_git_worktrees_provider.py
@@ -3,6 +3,7 @@ import shlex
 import shutil
 import subprocess
 import threading
+from dataclasses import replace
 from pathlib import Path

 import pytest
@@ -11,7 +12,7 @@ from devdoctor.ports import RealShell
 from devdoctor.providers import git_worktrees
 from devdoctor.providers._git import GitRunner, supports_merge_tree_write_tree
 from devdoctor.providers.git_worktrees import GitWorktreeProvider
-from devdoctor.types import AdviceAction, CommandAction, DiskUsage, Risk, ShellResult
+from devdoctor.types import AdviceAction, CommandAction, DiskUsage, Entry, Risk, ShellResult
 from tests.conftest import FakeShell

 needs_merge_tree = pytest.mark.skipif(
@@ -860,3 +861,160 @@ def test_integrated_worktree_holding_an_ignored_bare_repository_is_advice(
         check=False,
     )
     assert kept.stdout.strip() == "commit"
+
+
+# --- verification immediately before removal (#110) --------------------------------
+
+
+def _verify(path):
+    """Scan, then return a verifier and the worktree's reclaimable entry."""
+    entries, _ = _discover()
+    entry = _entry(entries, path)
+    assert entry.risk is Risk.RECLAIMABLE
+    return GitWorktreeProvider(RealShell()), entry
+
+
+def test_verify_accepts_an_unchanged_integrated_clean_worktree(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    _merge(app, worktree)
+    app.publish()
+    provider, entry = _verify(worktree.path)
+
+    assert provider.verify_removable(entry) is None
+
+
+def test_verify_refuses_a_commit_made_on_a_detached_head_after_the_scan(app, projects):
+    worktree = app.add_detached_worktree(projects / "wt" / "review")
+    app.publish()
+    provider, entry = _verify(worktree.path)
+
+    late = worktree.commit("Late work", {"late.txt": "late\n"})
+
+    assert provider.verify_removable(entry) == "not integrated"
+    assert app.git("cat-file", "-t", late) == "commit"
+
+
+def test_verify_accepts_a_later_commit_that_was_merged(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    _merge(app, worktree)
+    app.publish()
+    provider, entry = _verify(worktree.path)
+
+    worktree.commit("More", {"more.txt": "more\n"})
+    app.git("merge", "--no-ff", "-q", "-m", "Merge more", "feature")
+    app.publish()
+
+    assert provider.verify_removable(entry) is None
+
+
+def test_verify_refuses_an_untracked_file_added_after_the_scan(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    _merge(app, worktree)
+    app.publish()
+    provider, entry = _verify(worktree.path)
+
+    (worktree.path / "late.txt").write_text("late\n")
+
+    assert provider.verify_removable(entry) == "integrated, uncommitted changes"
+
+
+def test_verify_refuses_a_bare_repository_nested_after_the_scan(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    worktree.commit("Ignore vendor", {".gitignore": "vendor/\n"})
+    app.git("merge", "--no-ff", "-q", "-m", "Merge feature", "feature")
+    app.publish()
+    provider, entry = _verify(worktree.path)
+
+    subprocess.run(
+        ["git", "init", "--bare", "-q", str(worktree.path / "vendor" / "mirror.git")],
+        check=True,
+        capture_output=True,
+    )
+
+    assert provider.verify_removable(entry) == "contains nested repository"
+
+
+def test_verify_refuses_a_worktree_that_is_no_longer_registered(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    _merge(app, worktree)
+    app.publish()
+    provider, entry = _verify(worktree.path)
+
+    app.git("worktree", "remove", str(worktree.path))
+
+    assert provider.verify_removable(entry) == "no longer registered"
+
+
+def test_verify_refuses_an_entry_whose_action_is_not_the_removal(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    _merge(app, worktree)
+    app.publish()
+    provider, entry = _verify(worktree.path)
+    tampered = replace(entry, actions=(CommandAction(("git", "-C", "/elsewhere", "gc")),))
+
+    assert provider.verify_removable(tampered) == "could not verify: unexpected cleanup action"
+
+
+def test_verify_refuses_when_git_is_too_old():
+    version = ("git", "--no-optional-locks", "-C", "/", "version")
+    shell = FakeShell(responses={version: ShellResult(0, "git version 2.35.8\n", "")})
+    path = Path("/p/wt/feature")
+    entry = Entry(
+        provider="git-worktrees",
+        id=f"git-worktrees:{path}",
+        path=path,
+        label="app/feature · integrated",
+        size_bytes=1,
+        mtime=None,
+        risk=Risk.RECLAIMABLE,
+        recipe=[],
+        actions=(CommandAction(("git", "-C", "/p/app", "worktree", "remove", str(path))),),
+    )
+
+    assert (
+        GitWorktreeProvider(shell).verify_removable(entry)
+        == "cannot verify: git 2.35.8 is older than 2.36"
+    )
+
+
+def test_verify_never_raises(app, projects, monkeypatch):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    _merge(app, worktree)
+    app.publish()
+    provider, entry = _verify(worktree.path)
+
+    def boom(*args, **kwargs):
+        raise RuntimeError("boom")
+
+    monkeypatch.setattr(git_worktrees, "list_worktrees", boom)
+
+    assert provider.verify_removable(entry) == "could not verify: boom"
+
+
+@needs_merge_tree
+def test_verify_is_offline_and_write_free(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    worktree.commit("Feature", {"feature.txt": "feature\n"})
+    app.commit("Feature (squashed)", {"feature.txt": "feature\n"})
+    app.publish()
+    _, entry = _verify(worktree.path)
+    before = app.object_counts()
+    shell = RecordingShell()
+
+    assert GitWorktreeProvider(shell).verify_removable(entry) is None
+
+    assert app.object_counts() == before
+    assert any("merge-tree" in argv for argv, _ in shell.calls)
+    writing = {"fetch", "gc", "prune", "repair", "update-ref"}
+    object_dirs = set()
+    for argv, env in shell.calls:
+        assert env is not None
+        assert env["GIT_NO_LAZY_FETCH"] == "1"
+        assert env["GIT_TERMINAL_PROMPT"] == "0"
+        assert not writing & set(argv)
+        assert not {"worktree", "remove"} <= set(argv)
+        if env.get("GIT_OBJECT_DIRECTORY"):
+            assert "merge-tree" in argv
+            object_dirs.add(env["GIT_OBJECT_DIRECTORY"])
+    [object_dir] = object_dirs
+    assert not Path(object_dir).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_git_worktrees_provider.py -k verify -q`
Expected: 10 failures, each `AttributeError: 'GitWorktreeProvider' object has no attribute 'verify_removable'`.

- [ ] **Step 3: Implement**

Apply this change to `src/devdoctor/providers/git_worktrees.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/providers/git_worktrees.py b/src/devdoctor/providers/git_worktrees.py
--- a/src/devdoctor/providers/git_worktrees.py
+++ b/src/devdoctor/providers/git_worktrees.py
@@ -347,6 +347,51 @@ class GitWorktreeProvider(Provider):
             **_stat_kwargs(path),
         )

+    def verify_removable(self, entry: Entry) -> str | None:
+        """Re-classify ``entry`` against current state, immediately before removal (#110).
+
+        Returns None only if the worktree is still integrated and clean; otherwise the
+        state's label, or why it could not be verified. Never raises: a verifier must
+        answer, and every failure refuses the removal.
+        """
+        try:
+            return self._verify_removable(entry)
+        except Exception as exc:
+            return f"could not verify: {exc}"
+
+    def _verify_removable(self, entry: Entry) -> str | None:
+        target = _removal_target(entry)
+        if target is None:
+            return "could not verify: unexpected cleanup action"
+        repository, path = target
+        version = self._git.version()
+        if version is None:
+            return "cannot verify: git version unknown"
+        if not supports_worktree_list_z(version):
+            return f"cannot verify: git {'.'.join(map(str, version))} is older than 2.36"
+        try:
+            records = list_worktrees(self._git, repository)
+        except GitQueryError as exc:
+            return f"git error: {exc}"
+        real = _real(path)
+        record = next(
+            (r for r in self._linked_worktrees(repository, records) if _real(r.path) == real),
+            None,
+        )
+        if record is None:
+            return "no longer registered"
+        registered = frozenset(_real(r.path) for r in records)
+        objects_dir = (
+            self._create_objects_dir() if supports_merge_tree_write_tree(version) else None
+        )
+        try:
+            facts = self._repository_facts(repository, [], objects_dir)
+            state, _ = self._classify(facts, record, registered)
+        finally:
+            if objects_dir is not None:
+                self._remove_objects_dir(objects_dir)
+        return None if state is WorktreeState.INTEGRATED else state.value
+
     def _create_objects_dir(self) -> Path | None:
         try:
             return Path(tempfile.mkdtemp(prefix="devdoctor-merge-tree-"))
@@ -366,6 +411,19 @@ class GitWorktreeProvider(Provider):
             )


+def _removal_target(entry: Entry) -> tuple[Path, Path] | None:
+    """The repository and worktree of an entry this provider offered for removal, or None."""
+    if entry.path is None or len(entry.actions) != 1:
+        return None
+    [action] = entry.actions
+    if not isinstance(action, CommandAction):
+        return None
+    match action.argv:
+        case ("git", "-C", repository, "worktree", "remove", path) if path == str(entry.path):
+            return Path(repository), entry.path
+    return None
+
+
 def _repositories(candidates: GitCandidates) -> list[Path]:
     """Distinct repositories: roots the walk found, and those named by intact pointers."""
     seen: set[str] = set()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_git_worktrees_provider.py -q`
Expected: no failures (`test_verify_is_offline_and_write_free` skips only on git below 2.38).

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add src/devdoctor/providers/git_worktrees.py tests/test_git_worktrees_provider.py
git commit -m "feat(git-worktrees): re-classify a worktree on demand before removal" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Verify each worktree immediately before removal in CLI and web cleanup

**Files:**
- Modify: `src/devdoctor/cleanup.py`, `src/devdoctor/web/cleanup_runner.py`, `src/devdoctor/cli.py`, `src/devdoctor/web/routes_clean.py`
- Test: `tests/test_cleanup_core.py`, `tests/web/test_cleanup_runner.py`, `tests/test_worktree_containment_e2e.py`
- Docs: `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md`, `README.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `GitWorktreeProvider.verify_removable(entry) -> str | None` (Task 1); `containment.is_reclaimable_worktree` (existing).
- Produces (in `devdoctor.cleanup`): `VerifyRequired(entry: Entry)` (dataclass, part of `CleanupEvent`); `Verify = Callable[[Entry], str | None]`; `NO_VERIFIER_REASON = "cannot verify worktree removal"`; `async answer_verify(verify: Verify | None, entry: Entry) -> str | None`; `run(..., verify: Verify | None = None)`; `run_async(..., verify: Verify | None = None)`. `CleanupRunner.verify: Verify | None = None`.

- [ ] **Step 1: Write the failing tests**

Apply this change to `tests/test_cleanup_core.py` (for example with `git apply`):

```diff
diff --git a/tests/test_cleanup_core.py b/tests/test_cleanup_core.py
--- a/tests/test_cleanup_core.py
+++ b/tests/test_cleanup_core.py
@@ -1,12 +1,17 @@
+import threading
 from datetime import UTC, datetime
 from pathlib import Path

 from devdoctor.cleanup import (
+    NO_VERIFIER_REASON,
     ConfirmRequired,
     EntryResolved,
     ExecuteStep,
     PromptRequired,
+    VerifyRequired,
     iter_cleanup_events,
+    run,
+    run_async,
 )
 from devdoctor.types import (
     CleanResult,
@@ -234,10 +239,21 @@ def _content(id_: str, path: Path) -> Entry:
     )


-def _run_cleanup(report: Report, choices: dict[str, str], returncodes: dict[str, int]):
-    """Drive a cleanup: answer prompts by entry id, confirm, record executed entry ids."""
+def _run_cleanup(
+    report: Report,
+    choices: dict[str, str],
+    returncodes: dict[str, int],
+    refusals: dict[str, str] | None = None,
+    steps: list[tuple[str, str]] | None = None,
+):
+    """Drive a cleanup: answer prompts by entry id, confirm, record executed entry ids.
+
+    ``refusals`` answers ``VerifyRequired`` by entry id (absent ids pass); ``steps``
+    records ("verify" | "execute", entry id) in order.
+    """
     executed: list[str] = []
     results = {}
+    steps = [] if steps is None else steps
     gen = iter_cleanup_events(report, CleanupOpts(execute=True))
     try:
         event = next(gen)
@@ -246,7 +262,11 @@ def _run_cleanup(report: Report, choices: dict[str, str], returncodes: dict[str,
                 event = gen.send(choices[event.entry.id])
             elif isinstance(event, ConfirmRequired):
                 event = gen.send(True)
+            elif isinstance(event, VerifyRequired):
+                steps.append(("verify", event.entry.id))
+                event = gen.send((refusals or {}).get(event.entry.id))
             elif isinstance(event, ExecuteStep):
+                steps.append(("execute", event.entry.id))
                 executed.append(event.entry.id)
                 event = gen.send(ShellResult(returncodes.get(event.entry.id, 0), "", "refused"))
             else:
@@ -306,3 +326,130 @@ def test_contents_run_when_the_worktree_is_declined():

 def _ids(report: Report) -> list[str]:
     return [entry.id for entry in report.entries]
+
+
+def test_a_worktree_is_verified_immediately_before_its_removal():
+    report, inside, owner, outside = _worktree_report()
+    steps: list[tuple[str, str]] = []
+
+    _run_cleanup(report, dict.fromkeys(_ids(report), "y"), {}, steps=steps)
+
+    assert steps == [("verify", owner.id), ("execute", owner.id), ("execute", outside.id)]
+
+
+def test_a_worktree_that_changed_is_skipped_and_its_contents_run():
+    report, inside, owner, outside = _worktree_report()
+
+    executed, results = _run_cleanup(
+        report, dict.fromkeys(_ids(report), "y"), {}, refusals={owner.id: "not integrated"}
+    )
+
+    assert executed == [inside.id, outside.id]
+    assert results[owner.id] == CleanResult(
+        entry_id=owner.id,
+        status="skipped",
+        freed_bytes=0,
+        message="changed since the scan: not integrated; rescan before cleaning",
+    )
+    assert results[inside.id].status == "ok"
+    assert set(results) == set(_ids(report))
+
+
+def test_declined_worktrees_and_other_entries_are_never_verified():
+    report, inside, owner, outside = _worktree_report()
+    steps: list[tuple[str, str]] = []
+
+    _run_cleanup(report, {inside.id: "y", owner.id: "n", outside.id: "y"}, {}, steps=steps)
+
+    assert [step for step in steps if step[0] == "verify"] == []
+
+
+def test_preview_never_verifies():
+    report, *_ = _worktree_report()
+    events = list(iter_cleanup_events(report, CleanupOpts(execute=False)))
+    assert not any(isinstance(event, VerifyRequired) for event in events)
+
+
+class _NoShell:
+    def run(self, argv, *, check=False, timeout=None, env=None):
+        raise AssertionError(f"no command may run: {argv}")
+
+    def which(self, binary):
+        return None
+
+
+def test_run_without_a_verifier_never_removes_a_worktree():
+    owner = _worktree_owner()
+
+    results = run(
+        _report(owner),
+        shell=_NoShell(),
+        prompt_choice=lambda entry: "y",
+        confirm=lambda summary: True,
+        opts=CleanupOpts(execute=True),
+    )
+
+    assert [(r.status, r.message) for r in results] == [
+        ("skipped", f"changed since the scan: {NO_VERIFIER_REASON}; rescan before cleaning")
+    ]
+
+
+def test_run_removes_a_worktree_the_verifier_accepts():
+    owner = _worktree_owner()
+    ran: list[list[str]] = []
+    verified: list[str] = []
+
+    class _Shell(_NoShell):
+        def run(self, argv, *, check=False, timeout=None, env=None):
+            ran.append(argv)
+            return ShellResult(0, "", "")
+
+    results = run(
+        _report(owner),
+        shell=_Shell(),
+        prompt_choice=lambda entry: "y",
+        confirm=lambda summary: True,
+        opts=CleanupOpts(execute=True),
+        verify=lambda entry: verified.append(entry.id),
+    )
+
+    assert verified == [owner.id]
+    assert ran == [list(owner.actions[0].argv)]
+    assert [r.status for r in results] == ["ok"]
+
+
+async def test_run_async_verifies_off_the_event_loop_thread():
+    owner = _worktree_owner()
+    loop_thread = threading.get_ident()
+    verifier_threads: list[int] = []
+
+    def verify(entry):
+        verifier_threads.append(threading.get_ident())
+        return "integrated, uncommitted changes"
+
+    async def run_line(argv):
+        raise AssertionError("no command may run")
+
+    async def prompt(entry):
+        return "y"
+
+    async def confirm(summary):
+        return True
+
+    results = await run_async(
+        _report(owner),
+        run_line=run_line,
+        prompt_choice=prompt,
+        confirm=confirm,
+        opts=CleanupOpts(execute=True),
+        verify=verify,
+    )
+
+    assert len(verifier_threads) == 1
+    assert verifier_threads[0] != loop_thread
+    assert [(r.status, r.message) for r in results] == [
+        (
+            "skipped",
+            "changed since the scan: integrated, uncommitted changes; rescan before cleaning",
+        )
+    ]
```

Apply this change to `tests/web/test_cleanup_runner.py` (for example with `git apply`):

```diff
diff --git a/tests/web/test_cleanup_runner.py b/tests/web/test_cleanup_runner.py
--- a/tests/web/test_cleanup_runner.py
+++ b/tests/web/test_cleanup_runner.py
@@ -1,8 +1,9 @@
 import asyncio
+from pathlib import Path

 import pytest

-from devdoctor.types import CleanupOpts, ShellResult
+from devdoctor.types import CleanupOpts, CommandAction, Entry, Risk, ShellResult
 from devdoctor.web.cleanup_runner import CleanupRunner
 from devdoctor.web.runner_registry import RunnerRegistry
 from tests.test_cleanup_async import _e, _report
@@ -185,3 +186,44 @@ async def test_runner_multi_entry_attributes_events_to_correct_entry():
     # Both entries should have an execute_start event with their own id.
     assert set(starts) == {"A", "B"}
     await asyncio.wait_for(task, timeout=1)
+
+
+async def test_runner_skips_a_worktree_its_verifier_refuses():
+    path = "/p/wt/feature"
+    owner = Entry(
+        provider="git-worktrees",
+        id=f"git-worktrees:{path}",
+        path=Path(path),
+        label="app/feature · integrated",
+        size_bytes=1_000,
+        mtime=None,
+        risk=Risk.RECLAIMABLE,
+        recipe=[],
+        actions=(CommandAction(("git", "-C", "/p/app", "worktree", "remove", path)),),
+    )
+    verified = []
+
+    async def fake_run_line(_argv):
+        raise AssertionError("no command may run")
+
+    def verify(entry):
+        verified.append(entry.id)
+        return "not integrated"
+
+    runner = CleanupRunner(
+        report=_report(owner), opts=CleanupOpts(execute=True), run_line=fake_run_line, verify=verify
+    )
+    task = asyncio.create_task(runner.run())
+    assert (await runner.events.get())["event"] == "prompt"
+    await runner.answer_prompt(entry_id=owner.id, choice="y")
+    assert (await runner.events.get())["event"] == "awaiting_confirm"
+    await runner.answer_confirm(True)
+    event = await asyncio.wait_for(runner.events.get(), timeout=5)
+    while event["event"] != "done":
+        event = await asyncio.wait_for(runner.events.get(), timeout=5)
+    await task
+
+    assert verified == [owner.id]
+    assert [(r["status"], r["message"]) for r in event["data"]["results"]] == [
+        ("skipped", "changed since the scan: not integrated; rescan before cleaning")
+    ]
```

Apply this change to `tests/test_worktree_containment_e2e.py` (for example with `git apply`):

```diff
diff --git a/tests/test_worktree_containment_e2e.py b/tests/test_worktree_containment_e2e.py
--- a/tests/test_worktree_containment_e2e.py
+++ b/tests/test_worktree_containment_e2e.py
@@ -1,5 +1,6 @@
 """End to end: git worktree containment through scan, CLI and web (spec §8.4)."""

+import asyncio
 from datetime import UTC, datetime

 import pytest
@@ -7,6 +8,7 @@ from click.testing import CliRunner
 from httpx import ASGITransport, AsyncClient

 from devdoctor import cleanup, discovery
+from devdoctor import cli as cli_module
 from devdoctor.cli import build_cli
 from devdoctor.ports import RealShell
 from devdoctor.providers.git_worktrees import GitWorktreeProvider
@@ -146,7 +148,7 @@ def test_cli_clean_execute_removes_an_integrated_worktree(integrated, empty_path
     assert str(worktree.path) not in repo.git("worktree", "list", "--porcelain")


-def test_a_worktree_changed_after_the_scan_is_refused_by_git(integrated):
+def test_a_worktree_changed_after_the_scan_is_skipped_at_cleanup(integrated):
     _, worktree = integrated
     report = _scan()
     (worktree.path / "late.txt").write_text("written after the scan\n")
@@ -157,9 +159,98 @@ def test_a_worktree_changed_after_the_scan_is_refused_by_git(integrated):
         prompt_choice=lambda entry: "y",
         confirm=lambda summary: True,
         opts=CleanupOpts(execute=True),
+        verify=GitWorktreeProvider(RealShell()).verify_removable,
     )

     [result] = [r for r in results if r.entry_id.startswith("git-worktrees:")]
-    assert result.status == "error"
-    assert "untracked" in result.message
+    assert result.status == "skipped"
+    assert result.message == (
+        "changed since the scan: integrated, uncommitted changes; rescan before cleaning"
+    )
+    assert worktree.path.exists()
+
+
+def _detached_integrated(git_fixture, tmp_path):
+    """An integrated, clean worktree on a detached HEAD, as agent tooling creates them."""
+    repo = git_fixture.repository(tmp_path / "projects" / "app")
+    worktree = repo.add_detached_worktree(tmp_path / "projects" / "wt" / "agent")
+    repo.publish()
+    return repo, worktree
+
+
+def test_cli_clean_skips_a_worktree_committed_to_while_the_prompt_waits(
+    git_fixture, tmp_path, empty_paths_yaml, monkeypatch
+):
+    repo, worktree = _detached_integrated(git_fixture, tmp_path)
+    late: list[str] = []
+    results = []
+
+    def prompt_choice(entry):
+        # The race #110 is about: work is committed after the scan, before removal.
+        late.append(worktree.commit("Late work", {"late.txt": "late\n"}))
+        return "y"
+
+    def recording_run(*args, **kwargs):
+        results.extend(cleanup.run(*args, **kwargs))
+        return results
+
+    monkeypatch.setattr(cli_module, "real_prompts", lambda console: (prompt_choice, lambda s: True))
+    monkeypatch.setattr(cli_module, "cleanup_run", recording_run)
+
+    outcome = CliRunner().invoke(build_cli(GitOnlyShell()), ["clean", "--execute"])
+
+    assert outcome.exit_code == 0, outcome.output
+    [result] = [r for r in results if r.entry_id.startswith("git-worktrees:")]
+    assert result.status == "skipped"
+    assert result.message == "changed since the scan: not integrated; rescan before cleaning"
+    assert worktree.path.exists()
+    assert repo.git("cat-file", "-t", late[0]) == "commit"
+
+
+async def test_web_cleanup_skips_a_worktree_committed_to_before_confirmation(
+    git_fixture, tmp_path, empty_paths_yaml, monkeypatch
+):
+    repo, worktree = _detached_integrated(git_fixture, tmp_path)
+    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
+    app = build_app(GitOnlyShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
+    headers = {"Host": "testserver"}
+    registry = app.state.runner_registry
+    created = []
+    create = registry.create
+
+    def recording_create(factory):
+        created.append(create(factory))
+        return created[-1]
+
+    monkeypatch.setattr(registry, "create", recording_create)
+
+    async with AsyncClient(
+        transport=ASGITransport(app=app), base_url="http://testserver"
+    ) as client:
+        scan = (await client.get("/api/scan", headers=headers)).json()
+        [entry] = [e for e in scan["entries"] if e["provider"] == "git-worktrees"]
+        assert entry["risk"] == "reclaimable"
+
+        response = await client.post(
+            "/api/clean/jobs", json={"entry_ids": [entry["id"]]}, headers=headers
+        )
+        assert response.status_code == 200
+        [job] = created
+
+        event = await asyncio.wait_for(job.events.get(), timeout=10)
+        assert event["event"] == "prompt"
+        await job.answer_prompt(entry_id=entry["id"], choice="y")
+        event = await asyncio.wait_for(job.events.get(), timeout=10)
+        assert event["event"] == "awaiting_confirm"
+
+        late = worktree.commit("Late work", {"late.txt": "late\n"})
+        await job.answer_confirm(True)
+
+        while event["event"] != "done":
+            event = await asyncio.wait_for(job.events.get(), timeout=30)
+
+    [result] = [r for r in event["data"]["results"] if r["entry_id"] == entry["id"]]
+    assert result["status"] == "skipped"
+    assert result["message"] == "changed since the scan: not integrated; rescan before cleaning"
     assert worktree.path.exists()
+    assert repo.git("cat-file", "-t", late) == "commit"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_cleanup_core.py tests/web/test_cleanup_runner.py tests/test_worktree_containment_e2e.py -q`
Expected: `Interrupted: 1 error during collection` — `tests/test_cleanup_core.py` fails with `ImportError: cannot import name 'NO_VERIFIER_REASON' from 'devdoctor.cleanup'` (the other two files would fail on the unknown `verify=` argument, but collection stops first).

- [ ] **Step 3: Implement**

Apply this change to `src/devdoctor/cleanup.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/cleanup.py b/src/devdoctor/cleanup.py
--- a/src/devdoctor/cleanup.py
+++ b/src/devdoctor/cleanup.py
@@ -1,7 +1,8 @@
 from __future__ import annotations

+import asyncio
 import os
-from collections.abc import Generator
+from collections.abc import Callable, Generator
 from dataclasses import dataclass
 from typing import Literal

@@ -66,12 +67,28 @@ class ExecuteStep:
         return render_cleanup_action(self.action)


+@dataclass
+class VerifyRequired:
+    """Asks whether a worktree is still removable, immediately before it is removed.
+
+    The adapter answers ``None`` to proceed, or a reason to skip the removal.
+    """
+
+    entry: Entry
+
+
 @dataclass
 class EntryResolved:
     result: CleanResult


-CleanupEvent = PromptRequired | ConfirmRequired | ExecuteStep | EntryResolved
+CleanupEvent = PromptRequired | ConfirmRequired | VerifyRequired | ExecuteStep | EntryResolved
+
+# Re-checks an entry against current state: None if it is still removable, else why not.
+Verify = Callable[[Entry], str | None]
+
+# The answer when an adapter was given no verifier: never remove what cannot be re-checked.
+NO_VERIFIER_REASON = "cannot verify worktree removal"


 def iter_cleanup_events(report: Report, opts: CleanupOpts) -> Generator[CleanupEvent, object, None]:
@@ -79,6 +96,7 @@ def iter_cleanup_events(report: Report, opts: CleanupOpts) -> Generator[CleanupE

     - PromptRequired  -> send Choice ('y'/'n'/'a'/'s'/'q')
     - ConfirmRequired -> send bool
+    - VerifyRequired  -> send None to proceed, or a reason (str) to skip the entry
     - ExecuteStep     -> send ShellResult (adapter runs the shell)
     - EntryResolved   -> advance with next()

@@ -241,6 +259,19 @@ def _iter_execute(
                 )
             )
             continue
+        if is_reclaimable_worktree(entry):
+            # Git never re-checks integration, so re-classify right before removal (#110).
+            reason = yield VerifyRequired(entry)
+            if reason is not None:
+                yield EntryResolved(
+                    CleanResult(
+                        entry_id=entry.id,
+                        status="skipped",
+                        freed_bytes=0,
+                        message=f"changed since the scan: {reason}; rescan before cleaning",
+                    )
+                )
+                continue
         error_msg, executed = yield from _run_actions(entry)
         if executed and not error_msg and is_reclaimable_worktree(entry):
             removed[real[entry.id]] = entry
@@ -304,6 +335,7 @@ def run(
     prompt_choice: PromptChoice,
     confirm: Confirm,
     opts: CleanupOpts,
+    verify: Verify | None = None,
 ) -> list[CleanResult]:
     """Sync adapter over iter_cleanup_events. Preserves the v1 signature and behavior."""
     gen = iter_cleanup_events(report, opts)
@@ -316,6 +348,8 @@ def run(
             elif isinstance(event, ConfirmRequired):
                 summary = _confirm_summary(event)
                 event = gen.send(confirm(summary))
+            elif isinstance(event, VerifyRequired):
+                event = gen.send(NO_VERIFIER_REASON if verify is None else verify(event.entry))
             elif isinstance(event, ExecuteStep):
                 event = gen.send(shell.run(list(event.argv), check=False))
             elif isinstance(event, EntryResolved):
@@ -333,6 +367,7 @@ async def run_async(
     prompt_choice: AsyncPromptChoice,
     confirm: AsyncConfirm,
     opts: CleanupOpts,
+    verify: Verify | None = None,
 ) -> list[CleanResult]:
     """Async adapter over iter_cleanup_events. The web backend uses this."""
     gen = iter_cleanup_events(report, opts)
@@ -346,6 +381,8 @@ async def run_async(
             elif isinstance(event, ConfirmRequired):
                 summary = _confirm_summary(event)
                 event = gen.send(await confirm(summary))
+            elif isinstance(event, VerifyRequired):
+                event = gen.send(await answer_verify(verify, event.entry))
             elif isinstance(event, ExecuteStep):
                 event = gen.send(await run_line(event.argv))
             elif isinstance(event, EntryResolved):
@@ -356,6 +393,13 @@ async def run_async(
     return results


+async def answer_verify(verify: Verify | None, entry: Entry) -> str | None:
+    """Answer ``VerifyRequired`` off the event loop: verification runs git subprocesses."""
+    if verify is None:
+        return NO_VERIFIER_REASON
+    return await asyncio.to_thread(verify, entry)
+
+
 def _confirm_summary(event: ConfirmRequired) -> str:
     summary = (
         f"Execute cleanup for {len(event.approved)} entries, "
```

Apply this change to `src/devdoctor/web/cleanup_runner.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/web/cleanup_runner.py b/src/devdoctor/web/cleanup_runner.py
--- a/src/devdoctor/web/cleanup_runner.py
+++ b/src/devdoctor/web/cleanup_runner.py
@@ -41,6 +41,8 @@ class CleanupRunner:
     report: Report
     opts: CleanupOpts
     run_line: AsyncRunLine
+    # Re-checks a worktree immediately before removal (#110); None refuses every removal.
+    verify: cleanup_mod.Verify | None = None
     id: str = field(default_factory=lambda: uuid.uuid4().hex)
     storage: StorageBackend | None = None
     events: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
@@ -64,6 +66,8 @@ class CleanupRunner:
                         summary = cleanup_mod._confirm_summary(event)
                         confirmed = await self._confirm(summary)
                         event = gen.send(confirmed)
+                    elif isinstance(event, cleanup_mod.VerifyRequired):
+                        event = gen.send(await cleanup_mod.answer_verify(self.verify, event.entry))
                     elif isinstance(event, cleanup_mod.ExecuteStep):
                         result = await self._run_execute_step(
                             event.entry,
```

Apply this change to `src/devdoctor/cli.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/cli.py b/src/devdoctor/cli.py
--- a/src/devdoctor/cli.py
+++ b/src/devdoctor/cli.py
@@ -15,6 +15,7 @@ from devdoctor.cleanup import run as cleanup_run
 from devdoctor.config import load_app_settings
 from devdoctor.logging_config import configure_logging
 from devdoctor.ports import RealShell, Shell
+from devdoctor.providers.git_worktrees import GitWorktreeProvider
 from devdoctor.rendering import (
     real_prompts,
     render_diff_table,
@@ -214,6 +215,8 @@ def build_cli(shell: Shell | None = None) -> click.Group:  # noqa: PLR0915
                 allow_dangerous=allow_dangerous,
                 providers=frozenset(providers) if providers else None,
             ),
+            # Re-check each worktree immediately before removing it (#110).
+            verify=GitWorktreeProvider(ctx.obj["shell"]).verify_removable,
         )
         freed = sum(r.freed_bytes for r in results if r.status == "ok")
         failures = [r for r in results if r.status == "error"]
```

Apply this change to `src/devdoctor/web/routes_clean.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/web/routes_clean.py b/src/devdoctor/web/routes_clean.py
--- a/src/devdoctor/web/routes_clean.py
+++ b/src/devdoctor/web/routes_clean.py
@@ -10,6 +10,7 @@ from sse_starlette.sse import EventSourceResponse
 from starlette.responses import JSONResponse, Response

 from devdoctor import discovery, registry
+from devdoctor.providers.git_worktrees import GitWorktreeProvider
 from devdoctor.types import CleanupOpts, ScanFilters, ShellResult
 from devdoctor.web.cleanup_runner import CleanupRunner
 from devdoctor.web.models import CleanJobCreate, ConfirmAnswer, PromptAnswer
@@ -55,6 +56,8 @@ async def start_job(body: CleanJobCreate, request: Request) -> Response:
                     allow_dangerous=body.allow_dangerous,
                 ),
                 run_line=run_line,
+                # Re-check each worktree immediately before removing it (#110).
+                verify=GitWorktreeProvider(request.app.state.shell).verify_removable,
                 storage=request.app.state.storage,
             )
         )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_cleanup_core.py tests/test_cleanup_async.py tests/test_cleanup.py tests/web/test_cleanup_runner.py tests/web/test_routes_clean.py tests/test_worktree_containment_e2e.py tests/test_cli.py -q`
Expected: no failures.

- [ ] **Step 5: Update the documentation**

Apply this change to `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` (for example with `git apply`):

```diff
diff --git a/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md b/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
--- a/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
+++ b/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
@@ -328,11 +328,12 @@ repairs every broken worktree of that repository in one run.
 | Broken `.git` pointer (repository moved) | refused: validation failed |
 | Only a stash | removed; the stash survives, because it lives in the repository |

-The scan decides what is offered; git re-checks at execution, but only for
-what it refuses above. If a worktree gains uncommitted changes between scan
-and cleanup, git refuses and cleanup reports git's message as that entry's
-error. Git does not re-check integration: a commit made after the scan, on a
-detached HEAD, is left unreferenced when the worktree is removed (§11; #110).
+The scan decides what is offered. Git never re-checks integration, so cleanup
+re-classifies each worktree immediately before `git worktree remove` runs
+(see [`2026-09-15-worktree-cleanup-reverify-design.md`](2026-09-15-worktree-cleanup-reverify-design.md),
+#110): a worktree that is no longer integrated, clean and free of nested
+repositories is skipped. Git then applies its own refusals above, and cleanup
+reports git's message as that entry's error.

 ## 6. Containment, filters and cleanup

@@ -414,6 +415,13 @@ containment rules.
   running it would double-report freed bytes. Otherwise it runs normally — the
   worktree was declined, skipped, never reached, or git refused its removal.
   Paths are resolved before anything runs.
+- **Immediately before each approved reclaimable `git-worktrees` entry runs**, the
+  executor yields `VerifyRequired(entry)`. The CLI and web adapters answer with
+  `GitWorktreeProvider.verify_removable(entry)`, which re-classifies that worktree
+  against current state. A refusal resolves the entry as
+  `CleanResult(status="skipped", freed_bytes=0, message="changed since the scan:
+  <reason>; rescan before cleaning")`; the worktree is not counted as removed, so
+  approved entries inside it run normally (#110).
 - **CLI `clean` and `recipe` keep containment on.** They scan and act in one
   invocation, so ids cannot drift, and their `--provider` filter decides
   ownership consistently.
@@ -586,10 +594,12 @@ should land no later than PR 3.
   case-sensitively, so on a case-insensitive filesystem a project root spelled
   differently from git's recorded worktree path can miss containment, and those
   contents are counted and offered under their own provider as well.
-- **Commits made between classification and cleanup.** Integration is checked
-  against the HEAD read at scan time; if an agent commits in a detached,
-  integrated worktree before `git worktree remove` runs, the worktree still
-  removes cleanly and those commits become unreferenced.
+- **Verify-to-remove window.** Cleanup re-classifies a worktree immediately
+  before removing it (#110), which shrinks the gap between classification and
+  removal to the time between two subprocesses. A commit landing in that instant
+  can still be lost.
+- **Recipe script.** `devdoctor recipe` does not re-verify; review it against a
+  fresh scan before uncommenting a worktree removal.

 ## Appendix: measurement method

```

Apply this change to `README.md` (for example with `git apply`):

````diff
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -86,10 +86,8 @@ later; older git and partial clones detect only true merges and fast-forwards.
 A worktree holding another repository or worktree, even under an ignored path,
 is never offered, because `git worktree remove` would delete it. The contents of
 a removable worktree are counted once, under the worktree, instead of again by
-their own providers. Git re-checks for uncommitted changes when cleanup runs,
-so a worktree that gained uncommitted work after the scan is refused. If you
-commit in a worktree after scanning, rescan before cleaning
-([#110](https://github.com/katagun/devdoctor/issues/110)).
+their own providers. Cleanup re-checks each worktree immediately before removing
+it, so one that changed after the scan is skipped.

 ```bash
 devdoctor scan --provider git-worktrees
````

Apply this change to `CHANGELOG.md` (for example with `git apply`):

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -138,6 +138,12 @@ entries under a versioned heading as described in

 ### Fixed

+- **Cleanup re-checks each git worktree immediately before removing it.** Git
+  never re-checks whether a worktree is still integrated, so a commit made after
+  the scan, especially on a detached HEAD, could be lost when cleanup removed the
+  worktree. `devdoctor clean` and the web cleanup now re-classify every worktree
+  right before `git worktree remove` and skip any that changed, with the reason.
+  ([#110](https://github.com/katagun/devdoctor/issues/110))
 - **Filtered web scans no longer save partial auto-snapshots.** A scan with a
   risk, size or provider filter could be stored as an auto-snapshot and show up
   in history as a large drop followed by an equal jump. Only unfiltered scans are
```

- [ ] **Step 6: Run the full CI mirror**

Run each command from the Commands section.
Expected: ruff and format clean, mypy `Success: no issues found`, pytest with no failures (one CI-only skip).

- [ ] **Step 7: Commit**

```bash
git add src/devdoctor/cleanup.py src/devdoctor/web/cleanup_runner.py src/devdoctor/cli.py src/devdoctor/web/routes_clean.py tests/test_cleanup_core.py tests/web/test_cleanup_runner.py tests/test_worktree_containment_e2e.py docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md README.md CHANGELOG.md
git commit -m "fix(cleanup): re-check each git worktree immediately before removing it" -m "Closes #110." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Verify the PR and open it

**Files:** none.

- [ ] **Step 1: Run the full CI mirror**

Run each command from the Commands section.
Expected: all clean; pytest with no failures.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin fix/worktree-cleanup-reverify
gh pr create --base main --title "fix(cleanup): re-check each git worktree immediately before removal" --body "$(cat <<'EOF'
Implements #110 per docs/superpowers/specs/2026-09-15-worktree-cleanup-reverify-design.md.

`git worktree remove` never re-checks integration, so a commit made after the scan (especially on a detached HEAD) could be lost when cleanup removed the worktree.

## What

- `GitWorktreeProvider.verify_removable(entry)` re-runs the full classification on one worktree against current state and returns `None` only for "integrated, clean"; otherwise the state label or why it could not be verified. It never raises and follows the write-free, offline git contract.
- The cleanup state machine yields `VerifyRequired(entry)` immediately before each approved worktree removal. `cleanup.run`, `cleanup.run_async` and the web `CleanupRunner` answer it (async via `asyncio.to_thread`) and refuse without a verifier.
- `devdoctor clean` and `POST /api/clean/jobs` pass the provider's verifier. A refused worktree resolves as skipped ("changed since the scan: <reason>; rescan before cleaning") and its selected contents are cleaned normally.
- Provider spec §5.3, §6.4 and §11, README and CHANGELOG updated.

## Tests

- Real git: unchanged worktree accepted; a commit on a detached HEAD after the scan refused (commit intact); a later commit that was merged accepted; untracked file, nested bare repository and a pruned worktree refused; unexpected action, old git and internal errors refused; verification offline and write-free.
- State machine and adapters: verified only for approved worktrees, immediately before removal; refusals skip and let contents run; no verifier refuses; async verification runs off the event loop.
- End to end: `devdoctor clean --execute` and the web cleanup each skip a worktree committed to after the scan, and the commit survives.

Closes #110.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge once the required checks pass**

The required checks are `Python (lint, types, tests)` and `Web (typecheck, tests, build)`. Also read any CodeQL annotations. When everything passes, squash-merge with a message whose last line is the attribution trailer:

```bash
gh pr merge --squash --subject "fix(cleanup): re-check each git worktree immediately before removal (#<PR>)" --body "$(printf '%s\n' 'Cleanup re-classifies each git worktree immediately before git worktree remove, so one that changed after the scan is skipped (#110).' '' 'Closes #110.' '' 'Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>')"
```

If `--delete-branch` is not used or cannot delete the remote branch because `main` is checked out in another worktree, delete it after confirming the PR is merged: `git push origin :refs/heads/fix/worktree-cleanup-reverify`.
