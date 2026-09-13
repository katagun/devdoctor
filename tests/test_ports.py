import os
import subprocess

import pytest

from devdoctor.memory.providers import _NullShell
from devdoctor.ports import RealShell
from devdoctor.types import ShellResult
from tests.conftest import FakeShell


def test_real_shell_runs_command_and_returns_result():
    sh = RealShell()
    r = sh.run(["echo", "hello"])
    assert isinstance(r, ShellResult)
    assert r.returncode == 0
    assert r.stdout.strip() == "hello"
    assert r.stderr == ""


def test_real_shell_does_not_raise_on_nonzero_when_check_false():
    sh = RealShell()
    r = sh.run(["sh", "-c", "exit 3"], check=False)
    assert r.returncode == 3


def test_real_shell_which_finds_sh_and_missing_returns_none():
    sh = RealShell()
    assert sh.which("sh") is not None
    assert sh.which("definitely-not-a-real-binary-xyz") is None


def test_real_shell_captures_stderr_on_failure():
    sh = RealShell()
    r = sh.run(["sh", "-c", "echo err >&2; exit 1"], check=False)
    assert r.returncode == 1
    assert "err" in r.stderr


def test_real_shell_timeout_raises():
    sh = RealShell()
    with pytest.raises(subprocess.TimeoutExpired):
        sh.run(["sh", "-c", "sleep 5"], timeout=0.2)


def test_real_shell_env_adds_variables_on_top_of_the_inherited_environment(monkeypatch):
    monkeypatch.setenv("DEVDOCTOR_INHERITED_PROBE", "inherited")
    r = RealShell().run(
        ["sh", "-c", 'printf "%s|%s" "$DEVDOCTOR_ENV_PROBE" "$DEVDOCTOR_INHERITED_PROBE"'],
        env={"DEVDOCTOR_ENV_PROBE": "set"},
    )
    assert r.stdout == "set|inherited"


def test_real_shell_env_overrides_an_inherited_variable(monkeypatch):
    monkeypatch.setenv("DEVDOCTOR_ENV_PROBE", "inherited")
    r = RealShell().run(
        ["sh", "-c", 'printf "%s" "$DEVDOCTOR_ENV_PROBE"'],
        env={"DEVDOCTOR_ENV_PROBE": "override"},
    )
    assert r.stdout == "override"


def test_real_shell_env_does_not_leak_into_this_process(monkeypatch):
    monkeypatch.delenv("DEVDOCTOR_ENV_PROBE", raising=False)
    RealShell().run(["true"], env={"DEVDOCTOR_ENV_PROBE": "set"})
    assert "DEVDOCTOR_ENV_PROBE" not in os.environ


def test_real_shell_without_env_inherits_the_environment(monkeypatch):
    # Regression guard: this already passes before the change, and must keep passing.
    monkeypatch.setenv("DEVDOCTOR_INHERITED_PROBE", "inherited")
    r = RealShell().run(["sh", "-c", 'printf "%s" "$DEVDOCTOR_INHERITED_PROBE"'])
    assert r.stdout == "inherited"


def test_null_shell_accepts_env():
    r = _NullShell().run(["true"], env={"DEVDOCTOR_ENV_PROBE": "set"})
    assert r == ShellResult(returncode=1, stdout="", stderr="")


def test_fake_shell_records_env_alongside_calls():
    ok = ShellResult(returncode=0, stdout="", stderr="")
    shell = FakeShell(responses={("git", "status"): ok, ("ls",): ok})
    shell.run(["git", "status"], env={"GIT_TERMINAL_PROMPT": "0"})
    shell.run(["ls"])
    assert shell.calls == [("git", "status"), ("ls",)]
    assert shell.envs == [{"GIT_TERMINAL_PROMPT": "0"}, None]


def test_fake_shell_env_record_is_a_snapshot():
    ok = ShellResult(returncode=0, stdout="", stderr="")
    shell = FakeShell(responses={("x",): ok})
    env = {"A": "1"}
    shell.run(["x"], env=env)
    env["A"] = "2"
    assert shell.envs == [{"A": "1"}]
