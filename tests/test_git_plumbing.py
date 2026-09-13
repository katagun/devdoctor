import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from devdoctor.ports import RealShell
from devdoctor.providers._git import (
    GIT_CALL_TIMEOUT_S,
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
)
from devdoctor.types import ShellResult
from tests.conftest import FakeShell

SHA = "39014f227ec96b48d94c59dd54e6a5dc15566be4"

# Real `git worktree list --porcelain` output (git 2.50.1), fixture path replaced by /fx.
PORCELAIN = (
    "worktree /fx/repo\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /fx/wt/detached\n"
    f"HEAD {SHA}\n"
    "detached\n"
    "\n"
    "worktree /fx/wt/feature branch\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/feature\n"
    "\n"
    "worktree /fx/wt/gone\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/gone\n"
    "prunable gitdir file points to non-existent location\n"
    "\n"
    "worktree /fx/wt/locked-plain\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/lp\n"
    "locked\n"
    "\n"
    "worktree /fx/wt/locked-reason\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/lr\n"
    "locked agent running\n"
    "\n"
)

# Real porcelain output from a bare repository with one linked worktree.
BARE_PORCELAIN = (
    "worktree /fx/bare.git\n"
    "bare\n"
    "\n"
    "worktree /fx/wt/from-bare\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/main\n"
    "\n"
)

# Real `git status --porcelain --untracked-files=normal` output.
DIRTY_STATUS = ' M a\nR  b -> b2\nA  c\n M "file name"\n?? notes.txt\n?? scratch/\n'


def test_parse_worktree_porcelain_keeps_git_order_with_primary_first():
    paths = [record.path for record in parse_worktree_porcelain(PORCELAIN)]
    assert paths == [
        Path("/fx/repo"),
        Path("/fx/wt/detached"),
        Path("/fx/wt/feature branch"),
        Path("/fx/wt/gone"),
        Path("/fx/wt/locked-plain"),
        Path("/fx/wt/locked-reason"),
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
                lock_reason="agent running",
            ),
            id="locked-with-reason",
        ),
    ],
)
def test_parse_worktree_porcelain_record_shapes(path, expected):
    records = {str(record.path): record for record in parse_worktree_porcelain(PORCELAIN)}
    assert records[path] == expected


def test_parse_worktree_porcelain_bare_record_has_no_head():
    records = parse_worktree_porcelain(BARE_PORCELAIN)
    assert records[0] == WorktreeRecord(
        path=Path("/fx/bare.git"), head=None, branch=None, bare=True
    )
    assert records[1] == WorktreeRecord(path=Path("/fx/wt/from-bare"), head=SHA, branch="main")


def test_parse_worktree_porcelain_ignores_unknown_attributes():
    output = f"worktree /fx/repo\nHEAD {SHA}\nbranch refs/heads/main\nfuture-attribute x\n\n"
    assert parse_worktree_porcelain(output) == [
        WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
    ]


def test_parse_worktree_porcelain_empty_output():
    assert parse_worktree_porcelain("") == []


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


OFFLINE_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}
STATUS_ARGV = ("git", "--no-optional-locks", "-C", "/repo", "status", "--porcelain")


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


def test_runner_sets_offline_guards_on_every_call():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    runner = GitRunner(shell)
    runner.run(Path("/repo"), ["status", "--porcelain"])
    runner.run(Path("/repo"), ["status", "--porcelain"])
    assert shell.envs == [OFFLINE_ENV, OFFLINE_ENV]


def test_runner_adds_extra_env_to_the_offline_guards():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    GitRunner(shell).run(
        Path("/repo"), ["status", "--porcelain"], extra_env={"GIT_OBJECT_DIRECTORY": "/tmp/o"}
    )
    assert shell.envs == [{**OFFLINE_ENV, "GIT_OBJECT_DIRECTORY": "/tmp/o"}]


def test_offline_guards_cannot_be_overridden():
    assert git_env({"GIT_TERMINAL_PROMPT": "1", "GIT_NO_LAZY_FETCH": "0"}) == OFFLINE_ENV


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


def test_merge_tree_env_redirects_object_writes_and_reads_the_real_store():
    assert merge_tree_env(Path("/tmp/objects"), Path("/repo/.git")) == {
        "GIT_OBJECT_DIRECTORY": "/tmp/objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/repo/.git/objects",
    }


def test_version_is_read_through_the_contract():
    argv = ("git", "--no-optional-locks", "-C", "/", "version")
    ok = ShellResult(returncode=0, stdout="git version 2.50.1 (Apple Git-155)\n", stderr="")
    shell = FakeShell(responses={argv: ok})
    assert GitRunner(shell).version() == (2, 50, 1)
    assert shell.envs == [OFFLINE_ENV]


def test_version_is_none_when_git_fails():
    shell = _ScriptedShell(result=ShellResult(returncode=1, stdout="", stderr="boom"))
    assert GitRunner(shell).version() is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_real_git_accepts_the_invocation_contract():
    # Smoke test: the global options and environment are valid for the git on this machine.
    version = GitRunner(RealShell()).version()
    assert version is not None
    assert version >= (2, 0, 0)
