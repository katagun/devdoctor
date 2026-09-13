import os
import shutil
import threading
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
    worktree_belongs_to,
    worktree_status,
)
from devdoctor.providers._worktree_states import Integration
from devdoctor.types import ShellResult
from tests.conftest import FakeShell

REPO = Path("/r/app")
TREE = "a" * 40
OTHER_TREE = "b" * 40
HEAD = "c" * 40
COMMIT = "d" * 40
SYMBOLIC_REF = ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")


def _argv(directory: Path, *args: str) -> tuple[str, ...]:
    return ("git", "--no-optional-locks", "-C", str(directory), *args)


def _show_ref(ref: str) -> tuple[str, ...]:
    return _argv(REPO, "show-ref", "--verify", "--hash", ref)


def _rev_parse(revision: str) -> tuple[str, ...]:
    return _argv(REPO, "rev-parse", "--verify", "--quiet", revision)


def _resolves(
    ref: str, commit: str = COMMIT, tree: str = TREE
) -> dict[tuple[str, ...], ShellResult]:
    """Responses for a ref that exists and points at ``commit``."""
    return {
        _show_ref(ref): _ok(f"{commit}\n"),
        _rev_parse(f"{commit}^{{commit}}"): _ok(f"{commit}\n"),
        _rev_parse(f"{commit}^{{tree}}"): _ok(f"{tree}\n"),
    }


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
            _argv(REPO, *SYMBOLIC_REF): _ok("refs/remotes/origin/trunk\n"),
            **_resolves("refs/remotes/origin/trunk"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/trunk", COMMIT, TREE)


def test_default_branch_falls_back_to_origin_main_then_origin_master():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _exit(1),
            _show_ref("refs/remotes/origin/main"): _exit(128, "fatal: not a valid ref"),
            **_resolves("refs/remotes/origin/master"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/master", COMMIT, TREE)


def test_dangling_origin_head_falls_through_to_origin_main():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _ok("refs/remotes/origin/gone\n"),
            _show_ref("refs/remotes/origin/gone"): _exit(128, "fatal: not a valid ref"),
            **_resolves("refs/remotes/origin/main"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/main", COMMIT, TREE)


@pytest.mark.parametrize("target", ["--output=x", "refs/heads/main", "origin/main"])
def test_origin_head_outside_remote_refs_is_never_passed_to_git(target):
    git, shell = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _ok(f"{target}\n"),
            **_resolves("refs/remotes/origin/main"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/main", COMMIT, TREE)
    assert all(target not in call for call in shell.calls[1:])


def test_ref_that_names_no_commit_falls_through():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _exit(1),
            _show_ref("refs/remotes/origin/main"): _ok(f"{TREE}\n"),
            _rev_parse(f"{TREE}^{{commit}}"): _exit(1),
            **_resolves("refs/remotes/origin/master"),
        }
    )
    assert resolve_default_branch(git, REPO) == DefaultBranch("origin/master", COMMIT, TREE)


def test_no_default_branch_when_nothing_resolves():
    git, _ = _git(
        {
            _argv(REPO, *SYMBOLIC_REF): _exit(1),
            _show_ref("refs/remotes/origin/main"): _exit(128),
            _show_ref("refs/remotes/origin/master"): _exit(128),
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

DEFAULT = DefaultBranch("origin/main", COMMIT, TREE)
CONTEXT = MergeTreeContext(Path("/tmp/objects"), Path("/r/app/.git"))
MERGE_TREE = ("merge-tree", "--write-tree", COMMIT, HEAD)
IS_ANCESTOR = ("merge-base", "--is-ancestor", HEAD, COMMIT)


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
        {_argv(REPO, *MERGE_TREE): _exit(1, f"merge-tree: {COMMIT} - not something we can merge")}
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


# --- listing, ownership, status --------------------------------------------------


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


OWNERSHIP = ("rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir")


def _linked_worktree(tmp_path: Path, name: str = "feature") -> tuple[Path, Path]:
    """A repository's common dir and a worktree whose pointer files agree."""
    common = tmp_path / "app" / ".git"
    admin = common / "worktrees" / name
    admin.mkdir(parents=True)
    worktree = tmp_path / name
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {admin}\n")
    (admin / "gitdir").write_text(f"{worktree / '.git'}\n")
    return common, worktree


def test_worktree_belongs_through_a_symlink(tmp_path):
    common, worktree = _linked_worktree(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(worktree)
    git, _ = _git({_argv(link, *OWNERSHIP): _ok(f"{worktree}\n{common}\n")})
    assert worktree_belongs_to(git, link, common) is True


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param("/r/elsewhere\n{common}\n", id="different-toplevel"),
        pytest.param("{worktree}\n/r/elsewhere/.git\n", id="different-common-dir"),
        pytest.param("{worktree}\n", id="one-line"),
    ],
)
def test_worktree_does_not_belong_when_git_disagrees(tmp_path, stdout):
    common, worktree = _linked_worktree(tmp_path)
    answer = stdout.format(common=common, worktree=worktree)
    git, _ = _git({_argv(worktree, *OWNERSHIP): _ok(answer)})
    assert worktree_belongs_to(git, worktree, common) is False


def test_worktree_ownership_git_failure_raises(tmp_path):
    common, worktree = _linked_worktree(tmp_path)
    git, _ = _git({_argv(worktree, *OWNERSHIP): _exit(128, "fatal: detected dubious ownership")})
    with pytest.raises(GitQueryError, match="dubious ownership"):
        worktree_belongs_to(git, worktree, common)


def _no_pointer(common: Path, worktree: Path) -> None:
    (worktree / ".git").unlink()


def _pointer_is_a_directory(common: Path, worktree: Path) -> None:
    (worktree / ".git").unlink()
    (worktree / ".git").mkdir()


def _gitdir_missing(common: Path, worktree: Path) -> None:
    (worktree / ".git").write_text(f"gitdir: {common.parent / 'gone' / 'worktrees' / 'x'}\n")


def _admin_dir_of_another_repository(common: Path, worktree: Path) -> None:
    other = common.parent.parent / "other" / ".git" / "worktrees" / "feature"
    other.mkdir(parents=True)
    (other / "gitdir").write_text(f"{worktree / '.git'}\n")
    (worktree / ".git").write_text(f"gitdir: {other}\n")


def _admin_dir_names_another_worktree(common: Path, worktree: Path) -> None:
    (common / "worktrees" / "feature" / "gitdir").write_text(
        f"{common.parent / 'other' / '.git'}\n"
    )


def _admin_dir_without_gitdir_file(common: Path, worktree: Path) -> None:
    (common / "worktrees" / "feature" / "gitdir").unlink()


@pytest.mark.parametrize(
    "damage",
    [
        _no_pointer,
        _pointer_is_a_directory,
        _gitdir_missing,
        _admin_dir_of_another_repository,
        _admin_dir_names_another_worktree,
        _admin_dir_without_gitdir_file,
    ],
)
def test_worktree_does_not_belong_without_running_git(tmp_path, damage):
    common, worktree = _linked_worktree(tmp_path)
    damage(common, worktree)
    git, shell = _git({})
    assert worktree_belongs_to(git, worktree, common) is False
    assert shell.calls == []


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
        "origin/master", repo.rev("main"), repo.rev("main^{tree}")
    )
    repo.publish()
    assert resolve_default_branch(REAL_GIT, repo.path) == DefaultBranch(
        "origin/main", repo.rev("main"), repo.rev("main^{tree}")
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


def test_real_ownership_breaks_when_the_repository_moves(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    assert worktree_belongs_to(REAL_GIT, worktree.path, repo.path / ".git") is True
    shutil.move(repo.path, tmp_path / "moved")
    assert worktree_belongs_to(REAL_GIT, worktree.path, tmp_path / "moved" / ".git") is False


def test_real_ownership_follows_relative_paths(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    repo.git("worktree", "add", "-q", "--relative-paths", "-b", "rel", str(tmp_path / "rel"))
    assert worktree_belongs_to(REAL_GIT, tmp_path / "rel", repo.path / ".git") is True


def test_real_worktree_status(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    assert worktree_status(REAL_GIT, worktree.path).is_clean
    (worktree.path / "README").write_text("changed\n")
    (worktree.path / "new.txt").write_text("new\n")
    assert worktree_status(REAL_GIT, worktree.path) == StatusCounts(modified=1, untracked=1)


def test_real_default_branch_ignores_a_tag_named_like_a_remote_ref(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    base = repo.rev()
    repo.git("update-ref", "refs/remotes/origin/master", "main")
    unmerged = repo.commit("Unmerged", {"work.txt": "work\n"})
    # `rev-parse refs/remotes/origin/main` would find refs/tags/refs/remotes/origin/main.
    repo.git("tag", "refs/remotes/origin/main", unmerged)
    default = resolve_default_branch(REAL_GIT, repo.path)
    assert default is not None
    assert (default.name, default.commit) == ("origin/master", base)


def test_real_ownership_check_does_not_block_on_a_fifo_backlink(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "app")
    worktree = repo.add_worktree(tmp_path / "feature", "feature")
    backlink = repo.path / ".git" / "worktrees" / "feature" / "gitdir"
    backlink.unlink()
    os.mkfifo(backlink)
    outcome: list[bool] = []
    check = threading.Thread(
        target=lambda: outcome.append(
            worktree_belongs_to(REAL_GIT, worktree.path, repo.path / ".git")
        ),
        daemon=True,
    )
    check.start()
    check.join(timeout=10)
    assert outcome == [False]
