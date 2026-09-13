import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from devdoctor.ports import RealShell
from devdoctor.providers._git import (
    GIT_CALL_TIMEOUT_S,
    LOCAL_ENV_VARS,
    MERGE_TREE_MIN_VERSION,
    GitResult,
    GitRunner,
    StatusCounts,
    WorktreeRecord,
    git_env,
    merge_tree_env,
    parse_git_version,
    parse_status_porcelain,
    parse_worktree_porcelain,
    supports_merge_tree_write_tree,
    supports_worktree_list_z,
)
from devdoctor.types import ShellResult
from tests.conftest import FakeShell

SHA = "3b0239fd5161421987e2f6a664d86e12d9ce8aa4"

# Real `git worktree list --porcelain -z` output (git 2.50.1), fixture path replaced by /fx.
# Every field ends with NUL and an empty field ends a record. The lock reason and the last
# path contain real newlines, which only -z output carries unambiguously.
PORCELAIN_Z = (
    "worktree /fx/repo\0"
    f"HEAD {SHA}\0"
    "branch refs/heads/main\0"
    "\0"
    "worktree /fx/wt/detached\0"
    f"HEAD {SHA}\0"
    "detached\0"
    "\0"
    "worktree /fx/wt/feature branch\0"
    f"HEAD {SHA}\0"
    "branch refs/heads/feature\0"
    "\0"
    "worktree /fx/wt/gone\0"
    f"HEAD {SHA}\0"
    "branch refs/heads/gone\0"
    "prunable gitdir file points to non-existent location\0"
    "\0"
    "worktree /fx/wt/locked-plain\0"
    f"HEAD {SHA}\0"
    "branch refs/heads/lp\0"
    "locked\0"
    "\0"
    "worktree /fx/wt/locked-reason\0"
    f"HEAD {SHA}\0"
    "branch refs/heads/lr\0"
    'locked agent\nrunning "now"\0'
    "\0"
    "worktree /fx/wt/nl\npath\0"
    f"HEAD {SHA}\0"
    "branch refs/heads/nlpath\0"
    "\0"
)

# Real -z output from a bare repository with one linked worktree.
BARE_PORCELAIN_Z = (
    "worktree /fx/bare.git\0"
    "bare\0"
    "\0"
    "worktree /fx/wt/from-bare\0"
    f"HEAD {SHA}\0"
    "branch refs/heads/main\0"
    "\0"
)

# Real `git status --porcelain --untracked-files=normal` output.
DIRTY_STATUS = ' M a\nR  b -> b2\nA  c\n M "file name"\n?? notes.txt\n?? scratch/\n'

# `git rev-parse --local-env-vars` as printed by git 2.50.1.
GIT_2_50_LOCAL_ENV_VARS = (
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
OFFLINE_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}
# Every local variable removed (None), then the offline guards.
BASE_ENV = {**dict.fromkeys(LOCAL_ENV_VARS), **OFFLINE_ENV}
STATUS_ARGV = ("git", "--no-optional-locks", "-C", "/repo", "status", "--porcelain")

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def hermetic_git(tmp_path, monkeypatch):
    """A tmp directory where git sees no user or system configuration."""
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "t")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "t@t")
    return tmp_path


def _make_repo(path, *, message):
    path.mkdir(parents=True)
    _git("-c", "init.defaultBranch=main", "init", "-q", cwd=path)
    (path / "f").write_text(message + "\n")
    _git("add", "f", cwd=path)
    _git("commit", "-qm", message, cwd=path)
    return path


# ---------------------------------------------------------------- worktree list parser


def test_parse_worktree_porcelain_keeps_git_order_with_primary_first():
    paths = [record.path for record in parse_worktree_porcelain(PORCELAIN_Z)]
    assert paths == [
        Path("/fx/repo"),
        Path("/fx/wt/detached"),
        Path("/fx/wt/feature branch"),
        Path("/fx/wt/gone"),
        Path("/fx/wt/locked-plain"),
        Path("/fx/wt/locked-reason"),
        Path("/fx/wt/nl\npath"),
    ]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(
            "/fx/repo",
            WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
            id="on-branch",
        ),
        pytest.param(
            "/fx/wt/detached",
            WorktreeRecord(path=Path("/fx/wt/detached"), head=SHA, branch=None, detached=True),
            id="detached",
        ),
        pytest.param(
            "/fx/wt/feature branch",
            WorktreeRecord(path=Path("/fx/wt/feature branch"), head=SHA, branch="feature"),
            id="path-with-space",
        ),
        pytest.param(
            "/fx/wt/gone",
            WorktreeRecord(
                path=Path("/fx/wt/gone"),
                head=SHA,
                branch="gone",
                prunable=True,
                prunable_reason="gitdir file points to non-existent location",
            ),
            id="prunable-with-reason",
        ),
        pytest.param(
            "/fx/wt/locked-plain",
            WorktreeRecord(path=Path("/fx/wt/locked-plain"), head=SHA, branch="lp", locked=True),
            id="locked-without-reason",
        ),
        pytest.param(
            "/fx/wt/locked-reason",
            WorktreeRecord(
                path=Path("/fx/wt/locked-reason"),
                head=SHA,
                branch="lr",
                locked=True,
                lock_reason='agent\nrunning "now"',
            ),
            id="locked-with-raw-multiline-reason",
        ),
        pytest.param(
            "/fx/wt/nl\npath",
            WorktreeRecord(path=Path("/fx/wt/nl\npath"), head=SHA, branch="nlpath"),
            id="path-with-newline",
        ),
    ],
)
def test_parse_worktree_porcelain_record_shapes(path, expected):
    records = {str(record.path): record for record in parse_worktree_porcelain(PORCELAIN_Z)}
    assert records[path] == expected


def test_parse_worktree_porcelain_bare_record_has_no_head():
    records = parse_worktree_porcelain(BARE_PORCELAIN_Z)
    assert records[0] == WorktreeRecord(
        path=Path("/fx/bare.git"), head=None, branch=None, bare=True
    )
    assert records[1] == WorktreeRecord(path=Path("/fx/wt/from-bare"), head=SHA, branch="main")


def test_parse_worktree_porcelain_ignores_unknown_attributes():
    output = f"worktree /fx/repo\0HEAD {SHA}\0branch refs/heads/main\0future-attribute x\0\0"
    assert parse_worktree_porcelain(output) == [
        WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
    ]


def test_parse_worktree_porcelain_accepts_a_final_record_without_terminator():
    output = f"worktree /fx/repo\0HEAD {SHA}\0branch refs/heads/main\0"
    assert parse_worktree_porcelain(output) == [
        WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
    ]


def test_parse_worktree_porcelain_empty_output():
    assert parse_worktree_porcelain("") == []


@requires_git
def test_real_worktree_list_z_keeps_a_path_containing_a_newline(hermetic_git):
    repo = _make_repo(hermetic_git / "repo", message="base")
    worktree = hermetic_git / "wt" / "nl\npath"
    _git("worktree", "add", "-q", str(worktree), "-b", "nlpath", cwd=repo)
    runner = GitRunner(RealShell())
    if not supports_worktree_list_z(runner.version()):
        pytest.skip("git worktree list -z needs git 2.36")
    result = runner.run(repo, ["worktree", "list", "--porcelain", "-z"])
    assert result.ok, result.failure_summary()
    paths = [os.path.realpath(record.path) for record in parse_worktree_porcelain(result.stdout)]
    assert os.path.realpath(worktree) in paths


# ---------------------------------------------------------------- status parser


def test_parse_status_porcelain_counts_tracked_changes_and_untracked_entries():
    counts = parse_status_porcelain(DIRTY_STATUS)
    assert counts == StatusCounts(modified=4, untracked=2)
    assert counts.is_clean is False


def test_parse_status_porcelain_clean_worktree():
    counts = parse_status_porcelain("")
    assert counts == StatusCounts(modified=0, untracked=0)
    assert counts.is_clean is True


def test_parse_status_porcelain_does_not_count_ignored_entries():
    assert parse_status_porcelain("!! node_modules/\n") == StatusCounts(modified=0, untracked=0)


def test_parse_status_porcelain_counts_a_conflicted_entry_as_modified():
    # Real output for a merge conflict. A conflict must never read as clean.
    assert parse_status_porcelain("UU f\n") == StatusCounts(modified=1, untracked=0)


# ---------------------------------------------------------------- version helpers


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        pytest.param("git version 2.50.1 (Apple Git-155)\n", (2, 50, 1), id="apple"),
        pytest.param("git version 2.43.0\n", (2, 43, 0), id="linux"),
        pytest.param("git version 2.45.1.windows.1\n", (2, 45, 1), id="windows-suffix"),
        pytest.param("git version 2.39\n", (2, 39, 0), id="no-patch"),
        pytest.param("", None, id="empty"),
        pytest.param("not git at all\n", None, id="garbage"),
    ],
)
def test_parse_git_version(output, expected):
    assert parse_git_version(output) == expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        pytest.param(MERGE_TREE_MIN_VERSION, True, id="exactly-minimum"),
        pytest.param((2, 50, 1), True, id="newer"),
        pytest.param((2, 37, 9), False, id="older"),
        pytest.param(None, False, id="unknown"),
    ],
)
def test_supports_merge_tree_write_tree(version, expected):
    assert supports_merge_tree_write_tree(version) is expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        pytest.param((2, 36, 0), True, id="exactly-2.36"),
        pytest.param((2, 50, 1), True, id="newer"),
        pytest.param((2, 35, 9), False, id="older"),
        pytest.param(None, False, id="unknown"),
    ],
)
def test_supports_worktree_list_z(version, expected):
    assert supports_worktree_list_z(version) is expected


# ---------------------------------------------------------------- environment


def test_local_env_vars_cover_the_list_captured_from_git():
    assert set(GIT_2_50_LOCAL_ENV_VARS) <= set(LOCAL_ENV_VARS)


@requires_git
def test_local_env_vars_cover_the_installed_gits_list(tmp_path):
    listed = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    missing = sorted(set(listed) - set(LOCAL_ENV_VARS))
    assert not missing, f"add these to LOCAL_ENV_VARS: {missing}"


def test_git_env_removes_every_local_variable_and_sets_the_guards():
    assert git_env() == BASE_ENV


def test_offline_guards_cannot_be_overridden():
    assert git_env({"GIT_TERMINAL_PROMPT": "1", "GIT_NO_LAZY_FETCH": "0"}) == BASE_ENV


def test_extra_env_can_restore_a_local_variable():
    env = git_env(merge_tree_env(Path("/tmp/objects"), Path("/repo/.git")))
    assert env["GIT_OBJECT_DIRECTORY"] == "/tmp/objects"
    assert env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] == '"/repo/.git/objects"'
    assert env["GIT_DIR"] is None


@pytest.mark.parametrize(
    ("common_git_dir", "expected"),
    [
        pytest.param("/repo/.git", '"/repo/.git/objects"', id="plain"),
        pytest.param("/re:po/.git", '"/re:po/.git/objects"', id="colon"),
        pytest.param('/q"uote/.git', '"/q\\"uote/.git/objects"', id="double-quote"),
        pytest.param("/back\\slash/.git", '"/back\\\\slash/.git/objects"', id="backslash"),
        pytest.param("/new\nline/.git", '"/new\\nline/.git/objects"', id="newline"),
        pytest.param("/tab\tbed/.git", '"/tab\\tbed/.git/objects"', id="tab"),
    ],
)
def test_merge_tree_env_quotes_the_alternates_path(common_git_dir, expected):
    assert merge_tree_env(Path("/tmp/objects"), Path(common_git_dir)) == {
        "GIT_OBJECT_DIRECTORY": "/tmp/objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": expected,
    }


@requires_git
def test_real_runner_ignores_inherited_repository_variables(hermetic_git, monkeypatch):
    target = _make_repo(hermetic_git / "target", message="target-commit")
    other = _make_repo(hermetic_git / "other", message="other-commit")
    (other / "f").write_text("dirty\n")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    runner = GitRunner(RealShell())
    log = runner.run(target, ["log", "-1", "--format=%s"])
    status = runner.run(target, ["status", "--porcelain", "--untracked-files=normal"])
    assert log.stdout.strip() == "target-commit"
    assert parse_status_porcelain(status.stdout).is_clean


@requires_git
def test_real_runner_ignores_an_inherited_object_directory(hermetic_git, monkeypatch):
    target = _make_repo(hermetic_git / "target", message="target-commit")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(hermetic_git / "nowhere"))
    result = GitRunner(RealShell()).run(target, ["rev-parse", "HEAD"])
    assert result.ok, result.failure_summary()


@requires_git
def test_real_merge_tree_on_a_repo_path_with_a_colon_writes_nothing(hermetic_git):
    repo = _make_repo(hermetic_git / "re:po", message="base")
    _git("switch", "-qc", "feat", cwd=repo)
    (repo / "g").write_text("feat\n")
    _git("add", "g", cwd=repo)
    _git("commit", "-qm", "feat", cwd=repo)
    _git("switch", "-q", "main", cwd=repo)
    runner = GitRunner(RealShell())
    if not supports_merge_tree_write_tree(runner.version()):
        pytest.skip("git merge-tree --write-tree needs git 2.38")
    objects = hermetic_git / "tmp-objects"
    objects.mkdir()
    before = _git("count-objects", "-v", cwd=repo)
    result = runner.run(
        repo,
        ["merge-tree", "--write-tree", "main", "feat"],
        extra_env=merge_tree_env(objects, repo / ".git"),
    )
    assert result.ok, result.failure_summary()
    assert _git("count-objects", "-v", cwd=repo) == before


# ---------------------------------------------------------------- runner


@dataclass
class _ScriptedShell:
    """Shell double that records timeouts and can raise, which FakeShell cannot."""

    result: ShellResult = field(
        default_factory=lambda: ShellResult(returncode=0, stdout="", stderr="")
    )
    raises: BaseException | None = None
    timeouts: list[float | None] = field(default_factory=list)

    def run(self, argv, *, check=False, timeout=None, env=None):
        self.timeouts.append(timeout)
        if self.raises is not None:
            raise self.raises
        return self.result

    def which(self, binary):
        return None


def test_runner_uses_no_optional_locks_and_the_directory():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    GitRunner(shell).run(Path("/repo"), ["status", "--porcelain"])
    assert shell.calls == [STATUS_ARGV]


def test_runner_removes_local_variables_and_sets_guards_on_every_call():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    runner = GitRunner(shell)
    runner.run(Path("/repo"), ["status", "--porcelain"])
    runner.run(Path("/repo"), ["status", "--porcelain"])
    assert shell.envs == [BASE_ENV, BASE_ENV]


def test_runner_adds_extra_env_after_removing_local_variables():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    GitRunner(shell).run(
        Path("/repo"), ["status", "--porcelain"], extra_env={"GIT_OBJECT_DIRECTORY": "/tmp/o"}
    )
    assert shell.envs == [{**BASE_ENV, "GIT_OBJECT_DIRECTORY": "/tmp/o"}]


def test_runner_default_timeout_is_30_seconds():
    shell = _ScriptedShell()
    GitRunner(shell).run(Path("/repo"), ["status"])
    assert GIT_CALL_TIMEOUT_S == 30.0
    assert shell.timeouts == [30.0]


def test_runner_success_is_a_result():
    shell = _ScriptedShell(result=ShellResult(returncode=0, stdout="out\n", stderr=""))
    result = GitRunner(shell).run(Path("/repo"), ["status"])
    assert result == GitResult(
        returncode=0, stdout="out\n", stderr="", timed_out=False, timeout_s=30.0
    )
    assert result.ok is True


def test_runner_non_zero_exit_is_a_result_with_the_first_stderr_line():
    stderr = "fatal: not a git repository: /x\nhint: something else\n"
    shell = _ScriptedShell(result=ShellResult(returncode=128, stdout="", stderr=stderr))
    result = GitRunner(shell).run(Path("/x"), ["rev-parse", "--show-toplevel"])
    assert result.ok is False
    assert result.failure_summary() == "fatal: not a git repository: /x"


def test_runner_timeout_is_a_result_not_an_exception():
    shell = _ScriptedShell(raises=subprocess.TimeoutExpired(cmd=["git"], timeout=30.0))
    result = GitRunner(shell).run(Path("/repo"), ["merge-tree", "--write-tree", "main", "HEAD"])
    assert result.timed_out is True
    assert result.ok is False
    assert result.returncode is None
    assert result.failure_summary() == "timed out after 30 s"


def test_runner_launch_failure_is_a_result_not_an_exception():
    shell = _ScriptedShell(raises=FileNotFoundError(2, "No such file or directory", "git"))
    result = GitRunner(shell).run(Path("/repo"), ["status"])
    assert result.ok is False
    assert result.timed_out is False
    assert "No such file or directory" in result.failure_summary()


def test_failure_summary_without_stderr_names_the_exit_code():
    shell = _ScriptedShell(result=ShellResult(returncode=1, stdout="", stderr=""))
    result = GitRunner(shell).run(Path("/repo"), ["merge-base", "--is-ancestor", "a", "b"])
    assert result.failure_summary() == "exit 1"


def test_version_is_read_through_the_contract():
    argv = ("git", "--no-optional-locks", "-C", "/", "version")
    ok = ShellResult(returncode=0, stdout="git version 2.50.1 (Apple Git-155)\n", stderr="")
    shell = FakeShell(responses={argv: ok})
    assert GitRunner(shell).version() == (2, 50, 1)
    assert shell.envs == [BASE_ENV]


def test_version_is_none_when_git_fails():
    shell = _ScriptedShell(result=ShellResult(returncode=1, stdout="", stderr="boom"))
    assert GitRunner(shell).version() is None


@requires_git
def test_real_git_accepts_the_invocation_contract():
    # Smoke test: the global options and environment are valid for the git on this machine.
    version = GitRunner(RealShell()).version()
    assert version is not None
    assert version >= (2, 0, 0)
