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
