import os
import shlex
import shutil
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from devdoctor.ports import RealShell
from devdoctor.providers import git_worktrees
from devdoctor.providers._git import GitRunner, supports_merge_tree_write_tree
from devdoctor.providers._git_queries import GitQueryError
from devdoctor.providers.git_worktrees import GitWorktreeProvider
from devdoctor.types import (
    AdviceAction,
    CommandAction,
    DiskUsage,
    Entry,
    Refusal,
    RefusalKind,
    Risk,
    ShellResult,
)
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
        f"git-worktrees: 1 registered worktree(s) of {app.path} are missing or no longer "
        f'valid; run "git -C {app.path} worktree prune"'
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
    [object_dir] = object_dirs
    assert not Path(object_dir).exists()


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
        "git-worktrees: worktree listing needs git 2.36, found git 2.35.8; no worktrees reported"
    ]


def test_unknown_git_version_reports_nothing():
    version = ("git", "--no-optional-locks", "-C", "/", "version")
    shell = FakeShell(responses={version: ShellResult(1, "", "boom\n")})
    entries, provider = _discover(shell)
    assert entries == []
    assert provider.diagnostics == [
        "git-worktrees: could not determine the git version; no worktrees reported"
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


def _shadow_with_tag(app, worktree):
    app.git("tag", "origin/main", worktree.rev())


@pytest.mark.parametrize(
    ("branch", "shadow"),
    [
        pytest.param("feature", _shadow_with_tag, id="tag-named-origin-main"),
        pytest.param("origin/main", None, id="local-branch-named-origin-main"),
    ],
)
def test_refs_named_like_the_default_branch_do_not_shadow_it(app, projects, branch, shadow):
    worktree = app.add_worktree(projects / "wt" / "feature", branch)
    worktree.commit("Unmerged work", {"work.txt": "work\n"})
    app.git("update-ref", "refs/remotes/origin/main", "main")  # and no origin/HEAD
    if shadow is not None:
        shadow(app, worktree)

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label.endswith(" · not integrated")
    assert entry.risk is not Risk.RECLAIMABLE


def _does_not_point_back(repository):
    return (
        f"This worktree's .git does not point back to {repository}. Run "
        f'"git -C {repository} worktree repair", then rescan.'
    )


def test_directory_replaced_by_another_repository_is_a_broken_pointer(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    (worktree.path / ".git").unlink()
    subprocess.run(["git", "init", "-q", str(worktree.path)], capture_output=True, check=True)
    (worktree.path / ".gitignore").write_text("*\n")

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "app/feature · broken pointer"
    _assert_advice_shape(entry)
    assert _advice(entry) == _does_not_point_back(app.path)


def test_pointer_copied_from_another_worktree_is_a_broken_pointer(app, projects):
    first = app.add_worktree(projects / "wt" / "first", "first")
    second = app.add_worktree(projects / "wt" / "second", "second")
    _merge(app, first, branch="first")
    _merge(app, second, branch="second")
    app.publish()
    (second.path / ".git").write_text((first.path / ".git").read_text())

    entries = _discover()[0]

    entry = _entry(entries, second.path)
    assert entry.label == "app/second · broken pointer"
    _assert_advice_shape(entry)
    assert _advice(entry) == _does_not_point_back(app.path)
    assert _entry(entries, first.path).risk is Risk.RECLAIMABLE


def _ownership_argv(worktree):
    return (
        "git",
        "--no-optional-locks",
        "-C",
        str(worktree),
        "rev-parse",
        "--path-format=absolute",
        "--show-toplevel",
        "--git-common-dir",
    )


def test_ownership_timeout_with_an_intact_pointer_is_a_git_error(app, projects):
    slow = app.add_worktree(projects / "wt" / "slow", "slow")
    fast = app.add_worktree(projects / "wt" / "fast", "fast")
    _merge(app, slow, branch="slow")
    _merge(app, fast, branch="fast")
    app.publish()

    def intercept(argv):
        if argv == _ownership_argv(slow.path):
            raise subprocess.TimeoutExpired(list(argv), 30)

    entries, _ = _discover(RecordingShell(intercept))

    slow_entry = _entry(entries, slow.path)
    assert slow_entry.label == "app/slow · git error"
    _assert_advice_shape(slow_entry)
    assert _advice(slow_entry) == "git failed while checking this worktree: timed out after 30 s."
    assert _entry(entries, fast.path).risk is Risk.RECLAIMABLE


def test_unresolvable_git_directory_makes_every_worktree_a_git_error(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    common_dir = ("-C", str(app.path), "rev-parse", "--path-format=absolute", "--git-common-dir")

    def fail_common_dir(argv):
        return ShellResult(128, "", "fatal: bad config\n") if argv[2:] == common_dir else None

    shell = RecordingShell(fail_common_dir)
    entries, provider = _discover(shell)

    entry = _entry(entries, worktree.path)
    assert entry.label == "app/feature · git error"
    assert _advice(entry) == "git failed while checking this worktree: fatal: bad config."
    assert not any({"merge-tree", "merge-base", "status"} & set(argv) for argv, _ in shell.calls)
    assert provider.diagnostics == []


def test_every_reclaimable_command_removes_its_worktree(app, projects):
    app.commit("Ignore dependencies", {".gitignore": "node_modules/\n"})
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    (worktree.path / "node_modules" / "pkg").mkdir(parents=True)
    (worktree.path / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1;\n")
    _merge(app, worktree)
    app.publish()

    entries, _ = _discover()

    reclaimable = [e for e in entries if e.risk is Risk.RECLAIMABLE]
    assert [os.path.realpath(e.path) for e in reclaimable] == [os.path.realpath(worktree.path)]
    for entry in reclaimable:
        [action] = entry.actions
        assert isinstance(action, CommandAction)
        subprocess.run(action.argv, capture_output=True, check=True)
        assert not entry.path.exists()
        listed = app.git("worktree", "list", "--porcelain").splitlines()
        assert not {f"worktree {entry.path}", f"worktree {os.path.realpath(entry.path)}"} & set(
            listed
        )


def test_git_file_with_a_nul_byte_does_not_stop_discovery(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    odd = projects / "odd"
    odd.mkdir()
    (odd / ".git").write_text("gitdir: /tmp/a\0b/.git/worktrees/x\n")

    entries, _ = _discover()

    assert _entry(entries, worktree.path).risk is Risk.RECLAIMABLE
    assert not any(e.path == odd for e in entries)


_WRITING_COMMANDS = frozenset({"fetch", "gc", "prune", "repair", "update-ref"})


@needs_merge_tree
def test_discovery_runs_no_writing_command(app, projects):
    merged = app.add_worktree(projects / "wt" / "merged", "merged")
    _merge(app, merged, branch="merged")
    squashed = app.add_worktree(projects / "wt" / "squashed", "squashed")
    squashed.commit("Squashed feature", {"squashed.txt": "squashed\n"})
    app.commit("Squashed feature (squashed)", {"squashed.txt": "squashed\n"})
    app.publish()
    shell = RecordingShell()

    entries, _ = _discover(shell)

    assert _entry(entries, squashed.path).risk is Risk.RECLAIMABLE  # merge-tree ran
    assert _uses_merge_tree(shell)
    for argv, env in shell.calls:
        assert not _WRITING_COMMANDS & set(argv), argv
        assert not {"worktree", "remove"} <= set(argv), argv
        assert env is not None
        if env.get("GIT_OBJECT_DIRECTORY") is not None:
            assert "merge-tree" in argv, argv


def test_unregistered_broken_pointer_is_unverifiable(git_fixture, tmp_path, projects):
    repo = git_fixture.repository(tmp_path / "elsewhere" / "app")
    worktree = repo.add_worktree(projects / "wt" / "orphan", "orphan")
    shutil.rmtree(repo.path)

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "app/orphan · unverifiable"
    _assert_advice_shape(entry)


def test_worktree_of_a_bare_repository_is_classified_without_diagnostics(
    git_fixture, tmp_path, projects
):
    source = git_fixture.repository(tmp_path / "source")
    bare = projects / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(source.path), str(bare)],
        check=True,
        capture_output=True,
    )
    worktree = projects / "wt" / "feature"
    subprocess.run(
        ["git", "-C", str(bare), "worktree", "add", "-q", "-b", "feature", str(worktree), "main"],
        check=True,
        capture_output=True,
    )

    entries, provider = _discover()

    assert _entry(entries, worktree).label == "bare.git/feature · no default branch"
    assert provider.diagnostics == []


def test_worktree_on_an_unborn_branch_is_a_git_error(app, projects):
    version = GitRunner(RealShell()).version()
    if version is None or version < (2, 42, 0):
        pytest.skip("git worktree add --orphan needs git 2.42")
    app.publish()
    worktree = projects / "wt" / "empty"
    app.git("worktree", "add", "-q", "--orphan", "-b", "empty", str(worktree))

    entry = _entry(_discover()[0], worktree)

    assert entry.label == "app/empty · git error"
    assert entry.risk is Risk.DANGEROUS


def test_repository_reached_by_the_walk_and_a_pointer_is_listed_once(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    shell = RecordingShell()

    _discover(shell)

    listings = [argv for argv, _ in shell.calls if argv[4:6] == ("worktree", "list")]
    assert len(listings) == 1


def _nested_advice(relative):
    return (
        f"Contains another git repository or worktree at {relative}. git worktree remove "
        "would delete it, including uncommitted work. Move or remove it first."
    )


def test_integrated_worktree_holding_an_ignored_nested_worktree_is_advice(app, projects):
    app.commit("Ignore worktrees", {".gitignore": ".worktrees/\n"})
    outer = app.add_worktree(projects / "wt" / "outer", "outer")
    _merge(app, outer, branch="outer")
    app.publish()
    inner = outer.add_worktree(outer.path / ".worktrees" / "inner", "inner")
    (inner.path / "staged.txt").write_text("staged work\n")
    inner.git("add", "staged.txt")

    entries, _ = _discover()

    entry = _entry(entries, outer.path)
    assert entry.label == "app/outer · contains nested repository"
    assert entry.risk is not Risk.RECLAIMABLE
    _assert_advice_shape(entry)
    assert _advice(entry) == _nested_advice(".worktrees/inner")


def test_integrated_worktree_holding_an_ignored_nested_repository_is_advice(
    git_fixture, app, tmp_path
):
    app.commit("Ignore vendored code", {".gitignore": "vendor/\n"})
    # Outside every scan root, so only the walk inside the worktree can find the repository.
    outer = app.add_worktree(tmp_path / "elsewhere" / "outer", "outer")
    _merge(app, outer, branch="outer")
    app.publish()
    vendored = git_fixture.repository(outer.path / "vendor" / "lib")
    (vendored.path / "uncommitted.txt").write_text("uncommitted\n")

    entry = _entry(_discover()[0], outer.path)

    assert entry.label == "app/outer · contains nested repository"
    _assert_advice_shape(entry)
    assert _advice(entry) == _nested_advice("vendor/lib")


def test_integrated_worktree_with_ignored_dependencies_and_no_nested_git_is_reclaimable(
    app, projects
):
    app.commit("Ignore dependencies", {".gitignore": "node_modules/\n"})
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    (worktree.path / "node_modules" / "pkg" / "lib").mkdir(parents=True)
    (worktree.path / "node_modules" / "pkg" / "lib" / "index.js").write_text("x\n")
    _merge(app, worktree)
    app.publish()

    entry = _entry(_discover()[0], worktree.path)

    assert entry.label == "app/feature · integrated"
    assert entry.risk is Risk.RECLAIMABLE


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unreadable_directory_in_an_integrated_worktree_is_advice(app, projects):
    app.commit("Ignore sealed", {".gitignore": "sealed/\n"})
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    sealed = worktree.path / "sealed" / "inner"
    sealed.mkdir(parents=True)
    sealed.chmod(0o000)
    try:
        entry = _entry(_discover()[0], worktree.path)
    finally:
        sealed.chmod(0o755)

    assert entry.label == "app/feature · contains nested repository"
    _assert_advice_shape(entry)
    assert _advice(entry) == (
        "Could not read sealed/inner inside this worktree, so DevDoctor cannot rule out a "
        "nested repository that git worktree remove would delete."
    )


def test_no_offered_command_deletes_a_nested_worktree(app, projects):
    app.commit("Ignore worktrees", {".gitignore": ".worktrees/\n"})
    outer = app.add_worktree(projects / "wt" / "outer", "outer")
    _merge(app, outer, branch="outer")
    app.publish()
    inner = outer.add_worktree(outer.path / ".worktrees" / "inner", "inner")
    staged = inner.path / "staged.txt"
    staged.write_text("staged work\n")
    inner.git("add", "staged.txt")

    entries, _ = _discover()

    for entry in entries:
        for action in entry.actions:
            if isinstance(action, CommandAction):
                subprocess.run(action.argv, capture_output=True, check=False)
    assert staged.read_text() == "staged work\n"


def test_integrated_worktree_holding_an_ignored_bare_repository_is_advice(
    git_fixture, app, projects, tmp_path
):
    app.commit("Ignore vendored code", {".gitignore": "vendor/\n"})
    worktree = app.add_worktree(projects / "wt" / "bare", "bare")
    _merge(app, worktree, branch="bare")
    app.publish()
    mirror = worktree.path / "vendor" / "mirror.git"
    subprocess.run(["git", "init", "--bare", "-q", str(mirror)], check=True, capture_output=True)
    scratch = git_fixture.repository(tmp_path / "scratch")
    only_copy = scratch.commit("Exists only in the mirror", {"only.txt": "only\n"})
    scratch.git("push", "-q", str(mirror), "main")
    shutil.rmtree(scratch.path)

    entries, _ = _discover()

    entry = _entry(entries, worktree.path)
    assert entry.label == "app/bare · contains nested repository"
    assert entry.risk is not Risk.RECLAIMABLE
    _assert_advice_shape(entry)
    assert _advice(entry) == _nested_advice("vendor/mirror.git")
    for offered in entries:
        for action in offered.actions:
            if isinstance(action, CommandAction):
                subprocess.run(action.argv, capture_output=True, check=False)
    kept = subprocess.run(
        ["git", "--git-dir", str(mirror), "cat-file", "-t", only_copy],
        capture_output=True,
        text=True,
        check=False,
    )
    assert kept.stdout.strip() == "commit"


# --- verification immediately before removal (#110) --------------------------------


def _verify(path):
    """Scan, then return a verifier and the worktree's reclaimable entry."""
    entries, _ = _discover()
    entry = _entry(entries, path)
    assert entry.risk is Risk.RECLAIMABLE
    return GitWorktreeProvider(RealShell()), entry


def test_verify_accepts_an_unchanged_integrated_clean_worktree(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    assert provider.verify_removable(entry) is None


def test_verify_refuses_a_commit_made_on_a_detached_head_after_the_scan(app, projects):
    worktree = app.add_detached_worktree(projects / "wt" / "review")
    app.publish()
    provider, entry = _verify(worktree.path)

    late = worktree.commit("Late work", {"late.txt": "late\n"})

    assert provider.verify_removable(entry) == Refusal(RefusalKind.CHANGED, "not integrated")
    assert app.git("cat-file", "-t", late) == "commit"


def test_verify_refuses_a_commit_made_during_verification(app, projects, monkeypatch):
    """#110 final review: a commit landing after classification, not just after the scan."""
    worktree = app.add_detached_worktree(projects / "wt" / "review")
    app.publish()
    provider, entry = _verify(worktree.path)
    shas: list[str] = []
    original_check_nesting = git_worktrees.check_nesting

    def commit_then_check_nesting(*args, **kwargs):
        # The nesting walk is the last classification step (spec §5.1), so this lands
        # the commit after `_classify` has already decided the worktree is integrated.
        shas.append(worktree.commit("Mid-check", {"mid.txt": "mid\n"}))
        return original_check_nesting(*args, **kwargs)

    monkeypatch.setattr(git_worktrees, "check_nesting", commit_then_check_nesting)

    assert provider.verify_removable(entry) == Refusal(
        RefusalKind.CHANGED, "changed during verification"
    )
    assert app.git("cat-file", "-t", shas[0]) == "commit"


def test_verify_refuses_a_worktree_locked_during_verification(app, projects, monkeypatch):
    worktree = app.add_detached_worktree(projects / "wt" / "review")
    app.publish()
    provider, entry = _verify(worktree.path)
    original_check_nesting = git_worktrees.check_nesting

    def lock_then_check_nesting(*args, **kwargs):
        app.git("worktree", "lock", str(worktree.path))
        return original_check_nesting(*args, **kwargs)

    monkeypatch.setattr(git_worktrees, "check_nesting", lock_then_check_nesting)

    assert provider.verify_removable(entry) == Refusal(
        RefusalKind.CHANGED, "changed during verification"
    )


def test_verify_accepts_a_later_commit_that_was_merged(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    worktree.commit("More", {"more.txt": "more\n"})
    app.git("merge", "--no-ff", "-q", "-m", "Merge more", "feature")
    app.publish()

    assert provider.verify_removable(entry) is None


def test_verify_refuses_an_untracked_file_added_after_the_scan(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    (worktree.path / "late.txt").write_text("late\n")

    assert provider.verify_removable(entry) == Refusal(
        RefusalKind.CHANGED, "integrated, uncommitted changes"
    )


def test_verify_refuses_a_bare_repository_nested_after_the_scan(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    worktree.commit("Ignore vendor", {".gitignore": "vendor/\n"})
    app.git("merge", "--no-ff", "-q", "-m", "Merge feature", "feature")
    app.publish()
    provider, entry = _verify(worktree.path)

    subprocess.run(
        ["git", "init", "--bare", "-q", str(worktree.path / "vendor" / "mirror.git")],
        check=True,
        capture_output=True,
    )

    assert provider.verify_removable(entry) == Refusal(
        RefusalKind.CHANGED, "contains nested repository"
    )


def test_verify_refuses_a_worktree_that_is_no_longer_registered(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    app.git("worktree", "remove", str(worktree.path))

    assert provider.verify_removable(entry) == Refusal(RefusalKind.CHANGED, "no longer registered")


def test_verify_refuses_an_entry_whose_action_is_not_the_removal(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)
    tampered = replace(entry, actions=(CommandAction(("git", "-C", "/elsewhere", "gc")),))

    assert provider.verify_removable(tampered) == Refusal(
        RefusalKind.UNVERIFIED, "unexpected cleanup action"
    )


_GIT_VERSION = ("git", "--no-optional-locks", "-C", "/", "version")
_FAKE_WORKTREE = Path("/p/wt/feature")


def _fake_worktree_entry() -> Entry:
    return Entry(
        provider="git-worktrees",
        id=f"git-worktrees:{_FAKE_WORKTREE}",
        path=_FAKE_WORKTREE,
        label="app/feature · integrated",
        size_bytes=1,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=[],
        actions=(
            CommandAction(("git", "-C", "/p/app", "worktree", "remove", str(_FAKE_WORKTREE))),
        ),
    )


def test_verify_refuses_when_git_is_too_old():
    shell = FakeShell(responses={_GIT_VERSION: ShellResult(0, "git version 2.35.8\n", "")})

    assert GitWorktreeProvider(shell).verify_removable(_fake_worktree_entry()) == Refusal(
        RefusalKind.UNVERIFIED, "git 2.35.8 is older than 2.36"
    )


def test_verify_refuses_when_the_git_version_is_unknown():
    shell = FakeShell(responses={_GIT_VERSION: ShellResult(1, "", "boom\n")})

    assert GitWorktreeProvider(shell).verify_removable(_fake_worktree_entry()) == Refusal(
        RefusalKind.UNVERIFIED, "git version unknown"
    )


def test_verify_refuses_when_worktree_list_fails():
    listing = (
        "git",
        "--no-optional-locks",
        "-C",
        "/p/app",
        "worktree",
        "list",
        "--porcelain",
        "-z",
    )
    shell = FakeShell(
        responses={
            _GIT_VERSION: ShellResult(0, "git version 2.50.1\n", ""),
            listing: ShellResult(128, "", "fatal: not a git repository\n"),
        }
    )

    assert GitWorktreeProvider(shell).verify_removable(_fake_worktree_entry()) == Refusal(
        RefusalKind.UNVERIFIED, "git worktree list failed: fatal: not a git repository"
    )


def test_verify_refuses_a_worktree_deleted_but_not_pruned(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    shutil.rmtree(worktree.path)

    assert provider.verify_removable(entry) == Refusal(RefusalKind.CHANGED, "no longer registered")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_verify_reports_an_inaccessible_worktree_as_not_re_checked(app, projects):
    sealed = projects / "sealed"
    worktree = app.add_worktree(sealed / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    sealed.chmod(0o000)
    try:
        refusal = provider.verify_removable(entry)
    finally:
        sealed.chmod(0o755)

    assert refusal == Refusal(
        RefusalKind.UNVERIFIED, f"cannot access {worktree.path}: Permission denied"
    )


def test_verify_reports_a_git_failure_during_classification_as_not_re_checked(
    app, projects, monkeypatch
):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    def corrupt(*args, **kwargs):
        raise GitQueryError("fatal: index file corrupt")

    monkeypatch.setattr(git_worktrees, "worktree_status", corrupt)

    assert provider.verify_removable(entry) == Refusal(RefusalKind.UNVERIFIED, "git error")


def test_verify_never_raises(app, projects, monkeypatch):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    _merge(app, worktree)
    app.publish()
    provider, entry = _verify(worktree.path)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(git_worktrees, "list_worktrees", boom)

    assert provider.verify_removable(entry) == Refusal(RefusalKind.UNVERIFIED, "boom")


@needs_merge_tree
def test_verify_is_offline_and_write_free(app, projects):
    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    app.commit("Feature (squashed)", {"feature.txt": "feature\n"})
    app.publish()
    _, entry = _verify(worktree.path)
    before = app.object_counts()
    shell = RecordingShell()

    assert GitWorktreeProvider(shell).verify_removable(entry) is None

    assert app.object_counts() == before
    assert any("merge-tree" in argv for argv, _ in shell.calls)
    writing = {"fetch", "gc", "prune", "repair", "update-ref"}
    object_dirs = set()
    for argv, env in shell.calls:
        assert env is not None
        assert env["GIT_NO_LAZY_FETCH"] == "1"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert not writing & set(argv)
        assert not {"worktree", "remove"} <= set(argv)
        if env.get("GIT_OBJECT_DIRECTORY"):
            assert "merge-tree" in argv
            object_dirs.add(env["GIT_OBJECT_DIRECTORY"])
    [object_dir] = object_dirs
    assert not Path(object_dir).exists()


# --- _removal_target hardening (#110 final review) ----------------------------------


def _removal_entry(repository: str, action_path: str, entry_path: Path) -> Entry:
    return Entry(
        provider="git-worktrees",
        id="x",
        path=entry_path,
        label="app/feature · integrated",
        size_bytes=0,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=[],
        actions=(CommandAction(("git", "-C", repository, "worktree", "remove", action_path)),),
    )


@pytest.mark.parametrize(
    "repository, action_path, entry_path, expected",
    [
        pytest.param(
            "repo",
            "/p/wt/feature",
            Path("/p/wt/feature"),
            None,
            id="relative-repository",
        ),
        pytest.param(
            "/p/repo",
            "wt/feature",
            Path("wt/feature"),
            None,
            id="relative-entry-path",
        ),
        pytest.param(
            "/p/repo",
            "/p/wt/other",
            Path("/p/wt/feature"),
            None,
            id="action-path-differs-from-entry-path",
        ),
        pytest.param(
            "/p/repo",
            "/p/wt/feature",
            Path("/p/wt/feature"),
            (Path("/p/repo"), Path("/p/wt/feature")),
            id="well-formed-absolute-action",
        ),
    ],
)
def test_removal_target_requires_absolute_paths(repository, action_path, entry_path, expected):
    entry = _removal_entry(repository, action_path, entry_path)

    assert git_worktrees._removal_target(entry) == expected
