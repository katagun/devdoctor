from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from rich.console import Console

from devdoctor.rendering import render_diff_table, render_report_table
from devdoctor.types import DiffReport, DiffRow, Entry, Report, Risk


def _rep(*entries) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
    )


def _e(provider, id_, size, risk=Risk.SAFE, recipe=None):
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=risk,
        recipe=recipe or ["rm -rf /x"],
    )


def _render(fn, *args) -> str:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    fn(console, *args)
    return buf.getvalue()


def test_render_report_table_contains_entries_and_total():
    r = _rep(_e("ollama", "llama3:8b", 4_700_000_000), _e("uv-cache", "/x", 1_500_000_000))
    out = _render(render_report_table, r)
    assert "ollama" in out
    assert "uv-cache" in out
    assert "llama3:8b" in out
    # Total line
    assert "Total" in out


def test_render_report_table_handles_empty():
    out = _render(render_report_table, _rep())
    assert "No entries" in out or "Total" in out


def test_render_report_table_neutralizes_malicious_filenames():
    # A filename with Rich markup used to crash the render (MarkupError); one
    # with ANSI/OSC escapes used to reach the terminal. Both must be inert now.
    markup = Entry(
        provider="large-files",
        id="a",
        path=Path("/a"),
        label="/tmp/report[/].txt",  # malformed markup — would raise MarkupError
        size_bytes=1,
        mtime=None,
        risk=Risk.SAFE,
        recipe=["rm -rf /a"],
    )
    escapes = Entry(
        provider="large-files",
        id="b",
        path=Path("/b"),
        label="/tmp/evil\x1b[2J\x1b]0;pwned\x07end",  # screen-clear + title spoof
        size_bytes=1,
        mtime=None,
        risk=Risk.SAFE,
        recipe=["rm -rf /b"],
    )
    out = _render(render_report_table, _rep(markup, escapes))  # must not raise
    assert "\x1b[2J" not in out
    assert "\x1b]0;" not in out
    assert "report[/].txt" in out  # shown literally, not parsed


def test_render_diff_table_shows_deltas():
    d = DiffReport(
        before_at=datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC),
        after_at=datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC),
        rows=[
            DiffRow(
                provider="a", before_bytes=1000, after_bytes=200, delta_bytes=-800, delta_pct=-80.0
            ),
            DiffRow(provider="b", before_bytes=0, after_bytes=500, delta_bytes=500, delta_pct=0.0),
        ],
    )
    out = _render(render_diff_table, d)
    assert "a" in out
    assert "b" in out
    assert "-80" in out
