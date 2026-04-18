from diskdoctor.ports import RealShell
from diskdoctor.types import ShellResult


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
    import subprocess
    import pytest
    sh = RealShell()
    with pytest.raises(subprocess.TimeoutExpired):
        sh.run(["sh", "-c", "sleep 5"], timeout=0.2)
