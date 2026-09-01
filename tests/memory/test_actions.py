from __future__ import annotations

from tests.conftest import FakeShell

from devdoctor.memory.actions import execute_memory_action
from devdoctor.types import ShellResult


def _shell(**responses: ShellResult) -> FakeShell:
    # Keys are the argv strings joined by spaces for readability at call sites.
    return FakeShell(responses={tuple(k.split(" ")): v for k, v in responses.items()})


def test_terminate_kills_when_current_process_matches() -> None:
    sh = _shell(
        **{
            "ps -p 4242 -o comm=": ShellResult(0, "Google Chrome Helper\n", ""),
            "kill -TERM 4242": ShellResult(0, "", ""),
        }
    )
    result = execute_memory_action(
        sh,
        action_id="term",
        kind="terminate_process",
        target_id="pid:4242",
        confirmed=True,
        expected_name="Chrome Helper",
    )
    assert result.status == "ok"
    assert ("kill", "-TERM", "4242") in sh.calls


def test_terminate_refuses_when_pid_recycled_to_other_process() -> None:
    sh = _shell(**{"ps -p 4242 -o comm=": ShellResult(0, "bash\n", "")})
    result = execute_memory_action(
        sh,
        action_id="term",
        kind="terminate_process",
        target_id="pid:4242",
        confirmed=True,
        expected_name="Chrome Helper",
    )
    assert result.status == "error"
    assert "re-scan" in result.message
    # Crucially, we must NOT have signalled the recycled pid.
    assert ("kill", "-TERM", "4242") not in sh.calls


def test_terminate_refuses_when_process_gone() -> None:
    sh = _shell(**{"ps -p 4242 -o comm=": ShellResult(1, "", "")})
    result = execute_memory_action(
        sh,
        action_id="term",
        kind="terminate_process",
        target_id="pid:4242",
        confirmed=True,
        expected_name="Chrome Helper",
    )
    assert result.status == "error"
    assert "no longer running" in result.message
    assert ("kill", "-TERM", "4242") not in sh.calls


def test_terminate_without_expected_name_skips_revalidation() -> None:
    # Older clients that don't send a label keep the prior behavior.
    sh = _shell(**{"kill -TERM 4242": ShellResult(0, "", "")})
    result = execute_memory_action(
        sh,
        action_id="term",
        kind="terminate_process",
        target_id="pid:4242",
        confirmed=True,
    )
    assert result.status == "ok"
    assert ("kill", "-TERM", "4242") in sh.calls


def test_terminate_refuses_when_only_generic_token_matches() -> None:
    # A recycled pid now running a *different* helper shares only the generic
    # word "helper" with the expected name — that must NOT confirm a match.
    sh = _shell(**{"ps -p 4242 -o comm=": ShellResult(0, "Slack Helper\n", "")})
    result = execute_memory_action(
        sh,
        action_id="term",
        kind="terminate_process",
        target_id="pid:4242",
        confirmed=True,
        expected_name="Google Chrome Helper",
    )
    assert result.status == "error"
    assert "re-scan" in result.message
    assert ("kill", "-TERM", "4242") not in sh.calls


def test_terminate_matches_on_specific_shared_token() -> None:
    # "chrome" is specific, so the same program under a fuller comm still matches.
    sh = _shell(
        **{
            "ps -p 4242 -o comm=": ShellResult(0, "Google Chrome Helper\n", ""),
            "kill -TERM 4242": ShellResult(0, "", ""),
        }
    )
    result = execute_memory_action(
        sh,
        action_id="term",
        kind="terminate_process",
        target_id="pid:4242",
        confirmed=True,
        expected_name="Chrome Helper (Renderer)",
    )
    assert result.status == "ok"
    assert ("kill", "-TERM", "4242") in sh.calls


def test_terminate_refuses_system_pid() -> None:
    result = execute_memory_action(
        FakeShell(),
        action_id="term",
        kind="terminate_process",
        target_id="pid:1",
        confirmed=True,
        expected_name="launchd",
    )
    assert result.status == "error"
    assert "system process" in result.message


def test_unconfirmed_action_is_rejected() -> None:
    result = execute_memory_action(
        FakeShell(),
        action_id="term",
        kind="terminate_process",
        target_id="pid:4242",
        confirmed=False,
        expected_name="Chrome Helper",
    )
    assert result.status == "error"
    assert "confirmation" in result.message
