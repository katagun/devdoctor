from __future__ import annotations

import sys

from click.testing import CliRunner

from diskdoctor.cli import build_cli
from tests.conftest import FakeShell


def test_serve_help_lists_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(build_cli(FakeShell()), ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--no-browser" in result.output


def test_serve_without_web_extra_errors_clearly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Simulate missing web extras by forcing the `from diskdoctor.web.app import
    # build_app` line inside the serve command to raise ImportError. We patch
    # `diskdoctor.web.app` rather than `fastapi` directly because if fastapi
    # was already imported by a prior test in the same session, masking it in
    # sys.modules leaks past the CLI's try/except (fastapi re-imports itself
    # internally during route registration). Patching the web.app module is
    # both accurate (that's exactly what the web extra installs) and robust.
    monkeypatch.setitem(sys.modules, "diskdoctor.web.app", None)
    runner = CliRunner()
    result = runner.invoke(build_cli(FakeShell()), ["serve", "--port", "0", "--no-browser"])
    assert result.exit_code != 0
    assert "uv tool install" in result.output or "install" in result.output.lower()
