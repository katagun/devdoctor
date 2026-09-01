from __future__ import annotations

import logging
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from devdoctor import discovery
from devdoctor.config import default_app_settings, load_app_settings
from devdoctor.logging_config import configure_logging
from devdoctor.providers.base import PathProvider
from devdoctor.rendering import render_report_table
from devdoctor.types import Entry, Report, Risk, ScanFilters
from tests.conftest import FakeShell


@pytest.fixture(autouse=True)
def _propagate_devdoctor_logs():
    """Let caplog (whose handler sits on the root logger) see our records.

    configure_logging sets propagate=False on the `devdoctor` logger to avoid
    double output under uvicorn; that would otherwise hide records from caplog.
    Force propagation for the duration of each test, then restore.
    """
    logger = logging.getLogger("devdoctor")
    previous = logger.propagate
    logger.propagate = True
    try:
        yield
    finally:
        logger.propagate = previous


# --- configure_logging ------------------------------------------------------


def test_configure_logging_sets_info_by_default() -> None:
    configure_logging(False)
    assert logging.getLogger("devdoctor").level == logging.INFO


def test_configure_logging_verbose_sets_debug() -> None:
    configure_logging(True)
    assert logging.getLogger("devdoctor").level == logging.DEBUG
    # Reset for other tests / suites.
    configure_logging(False)


def test_configure_logging_does_not_add_duplicate_handlers() -> None:
    logger = logging.getLogger("devdoctor")
    configure_logging(False)
    count = len(logger.handlers)
    configure_logging(True)
    configure_logging(False)
    assert len(logger.handlers) == count


# --- config warning ---------------------------------------------------------


def test_corrupt_config_logs_warning_and_falls_back(tmp_path: Path, caplog) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ this is not valid json ")
    with caplog.at_level(logging.WARNING, logger="devdoctor.config"):
        settings = load_app_settings(path)
    # Same behaviour as before: defaults are returned.
    assert settings == default_app_settings()
    # ...but now the failure is logged, naming the path.
    assert any(str(path) in rec.message for rec in caplog.records)
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_non_object_config_logs_warning(tmp_path: Path, caplog) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]")
    with caplog.at_level(logging.WARNING, logger="devdoctor.config"):
        load_app_settings(path)
    assert any("not a JSON object" in rec.message for rec in caplog.records)


# --- scan diagnostics channel ----------------------------------------------


def _path_provider(root: Path) -> PathProvider:
    return PathProvider(
        FakeShell(),
        name="test-cache",
        description="test",
        platforms=("darwin", "linux"),
        risk=Risk.SAFE,
        raw_paths=(str(root),),
        recipe_template=["rm -rf {path}"],
    )


def test_scan_surfaces_skipped_path_in_diagnostics(tmp_path: Path, caplog) -> None:
    root = tmp_path / "cache"
    protected = root / "protected"
    protected.mkdir(parents=True)
    (protected / "hidden.txt").write_bytes(b"x" * 20)
    (root / "readable.txt").write_bytes(b"y" * 10)
    protected.chmod(0o000)
    try:
        provider = _path_provider(root)
        with caplog.at_level(logging.WARNING, logger="devdoctor.providers.base"):
            report = discovery.scan([provider], ScanFilters(), datetime.now(UTC))
        # The unreadable dir was skipped during sizing and surfaced as a
        # diagnostic (control flow unchanged — the readable entry still shows).
        assert report.diagnostics, "expected at least one diagnostic"
        assert any("test-cache" in msg for msg in report.diagnostics)
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)
    finally:
        protected.chmod(0o755)


def test_scan_without_errors_has_empty_diagnostics(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    (root / "f.txt").write_bytes(b"z" * 100)
    report = discovery.scan([_path_provider(root)], ScanFilters(), datetime.now(UTC))
    assert report.diagnostics == []


# --- rendering surfaces diagnostics ----------------------------------------


def _render(report: Report) -> str:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    render_report_table(console, report)
    return buf.getvalue()


def _report_with(diagnostics: list[str]) -> Report:
    e = Entry("p", "1", Path("/x"), "p/1", 100, None, Risk.SAFE, ["rm -rf /x"])
    return Report(
        entries=[e],
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
        diagnostics=diagnostics,
    )


def test_render_shows_diagnostic_note_when_present() -> None:
    out = _render(_report_with(["test-cache: skipped 2 path(s) while sizing"]))
    assert "diagnostic" in out
    assert "skipped" in out


def test_render_omits_diagnostics_when_empty() -> None:
    out = _render(_report_with([]))
    assert "diagnostic" not in out
