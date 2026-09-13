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


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_inaccessible_worktree_is_a_diagnostic_and_the_others_classify(app, projects, tmp_path):
    accessible = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, accessible)
    hidden = app.add_worktree(tmp_path / "sealed" / "hidden", "hidden")
    _merge(app, hidden, branch="hidden")
    app.publish()
    sealed_dir = tmp_path / "sealed"
    sealed_dir.chmod(0o000)
    try:
        entries, provider = _discover()

        assert _entry(entries, accessible.path).risk is Risk.RECLAIMABLE
        assert not any(e.path == hidden.path for e in entries)
        assert provider.diagnostics == [
            f"git-worktrees: could not access registered worktree {hidden.path} "
            "(Permission denied); not reported"
        ]
    finally:
        sealed_dir.chmod(0o755)
