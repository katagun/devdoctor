import dataclasses
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from rich.console import Console

from devdoctor.cleanup import (
    ConfirmRequired,
    EntryResolved,
    ExecuteStep,
    PlannedEntry,
    SkippedEntry,
)
from devdoctor.discovery import ProviderFinished, ProviderStarted, ScanStarted
from devdoctor.rendering import CleanupPresenter, render_diff_table, render_report_table
from devdoctor.types import (
    AdviceAction,
    CleanResult,
    DeletePathAction,
    DiffReport,
    DiffRow,
    Entry,
    ProviderTiming,
    Report,
    Risk,
)


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
    assert "Footprint" in out
    assert "estimated reclaimable" in out


def test_render_report_table_handles_empty():
    out = _render(render_report_table, _rep())
    assert "No entries" in out or "Footprint" in out


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


HOME = Path("/Users/me")


def _console() -> Console:
    return Console(record=True, width=140, force_terminal=False, color_system=None)


def _entry(id_: str, size: int | None, risk: Risk = Risk.SAFE, provider: str = "uv-cache") -> Entry:
    path = HOME / ".cache" / id_
    return Entry(
        provider=provider,
        id=id_,
        path=path,
        label=str(path),
        size_bytes=size or 0,
        mtime=None,
        risk=risk,
        recipe=[],
        actions=(DeletePathAction(path, recursive=True),),
    )


def _planned(entry: Entry, estimate: int | None = None) -> PlannedEntry:
    est = entry.size_bytes if estimate is None else estimate
    return PlannedEntry(entry=entry, actions=entry.actions, estimate_bytes=est)


def test_plan_table_lists_every_entry_with_human_sizes_and_the_command() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    uv = _entry("uv", 5_600_000_000)
    hint = _entry("hint", 0, provider="docker-vm-disk", risk=Risk.RECLAIMABLE)
    hint = dataclasses.replace(hint, actions=(AdviceAction("shrink the disk image"),))
    dangerous = _entry("x", 1, risk=Risk.DANGEROUS)
    p.on_event(
        ConfirmRequired(
            approved=[uv, hint],
            total_bytes=5_600_000_000,
            unknown_entries=1,
            plan=(_planned(uv), _planned(hint, None)),
            skipped=(SkippedEntry(dangerous, "dangerous (pass --allow-dangerous to include)"),),
        )
    )

    out = console.export_text()
    assert "Cleanup plan — 2 entries, ~5.2G estimated (+1 unknown)" in out
    assert "uv-cache" in out and "~/.cache/uv" in out and "5.2G" in out
    assert "rm -rf -- /Users/me/.cache/uv" in out
    assert "docker-vm-disk" in out and "unknown" in out and "echo 'shrink the disk image'" in out
    assert "Not in this run: 1 dangerous (pass --allow-dangerous to include)" in out
    assert p.plan[0].entry.id == "uv"


def test_progress_lines_show_status_and_the_failure_reason() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    uv, pip = _entry("uv", 5_600_000_000), _entry("pip", 700_000_000, provider="pip-cache")
    p.on_event(
        ConfirmRequired(
            approved=[uv, pip], total_bytes=6_300_000_000, plan=(_planned(uv), _planned(pip))
        )
    )
    p.on_event(ExecuteStep(entry=uv, action=uv.actions[0]))
    p.on_event(
        EntryResolved(
            CleanResult(
                entry_id="uv",
                status="error",
                freed_bytes=0,
                message="error: failed to clean\nsecond line",
            )
        )
    )
    p.on_event(
        EntryResolved(
            CleanResult(
                entry_id="pip",
                status="ok",
                freed_bytes=700_000_000,
                message="cleanup succeeded; byte count is an estimate",
            )
        )
    )

    out = console.export_text()
    assert "[1/2] ✗ uv-cache" in out and "failed: error: failed to clean" in out
    assert "second line" not in out
    assert "[2/2] ✓ pip-cache" in out and "~667.6M" in out


def test_summary_states_estimates_and_the_free_space_delta() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    uv, pip = _entry("uv", 5_600_000_000), _entry("pip", 700_000_000, provider="pip-cache")
    p.on_event(
        ConfirmRequired(
            approved=[uv, pip], total_bytes=6_300_000_000, plan=(_planned(uv), _planned(pip))
        )
    )
    results = [
        CleanResult(entry_id="uv", status="error", freed_bytes=0, message="boom"),
        CleanResult(entry_id="pip", status="ok", freed_bytes=700_000_000),
        CleanResult(entry_id="x", status="skipped", freed_bytes=0, message="declined"),
    ]
    p.summary(results, free_before=70_000_000_000, free_after=70_200_000_000)

    out = console.export_text()
    assert "Done: 1 ok · 1 failed · 1 skipped" in out
    assert "~667.6M estimated reclaimed of ~5.9G planned" in out
    assert "free space 65.2G → 65.4G (+190.7M)" in out
    assert "APFS local snapshots can hold freed blocks" in out
    assert "recorded: devdoctor history" in out


def test_summary_omits_the_snapshot_hint_when_space_was_freed() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    pip = _entry("pip", 700_000_000, provider="pip-cache")
    p.on_event(ConfirmRequired(approved=[pip], total_bytes=700_000_000, plan=(_planned(pip),)))
    p.summary(
        [CleanResult(entry_id="pip", status="ok", freed_bytes=700_000_000)],
        free_before=1_000_000_000,
        free_after=1_700_000_000,
    )
    out = console.export_text()
    assert "APFS" not in out and "free space" in out


def test_summary_omits_the_snapshot_hint_when_delta_is_exactly_half_reclaimed() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    pip = _entry("pip", 700_000_000, provider="pip-cache")
    p.on_event(ConfirmRequired(approved=[pip], total_bytes=700_000_000, plan=(_planned(pip),)))
    p.summary(
        [CleanResult(entry_id="pip", status="ok", freed_bytes=700_000_000)],
        free_before=1_000_000_000,
        free_after=1_000_000_000 + 350_000_000,  # exactly reclaimed / 2
    )
    out = console.export_text()
    assert "APFS" not in out


def test_summary_states_nothing_to_clean_when_nothing_was_approved() -> None:
    # No ConfirmRequired at all: nothing was approved, so the plan was never printed.
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    results = [
        CleanResult(
            entry_id="x",
            status="skipped",
            freed_bytes=0,
            message="dangerous (pass --allow-dangerous to include)",
        ),
        CleanResult(entry_id="y", status="skipped", freed_bytes=0, message="declined"),
    ]
    p.summary(results, free_before=None, free_after=None)
    out = console.export_text()
    assert "Nothing to clean: 1 dangerous (pass --allow-dangerous to include), 1 declined" in out


def test_summary_counts_dry_run_as_previewed_not_skipped() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    results = [
        CleanResult(
            entry_id="x", status="dry_run", freed_bytes=100, message="byte count is an estimate"
        )
    ]
    p.summary(results, free_before=None, free_after=None)
    out = console.export_text()
    assert "0 skipped" in out
    assert "1 previewed" in out


def test_summary_without_disk_figures_omits_the_delta() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    p.on_event(ConfirmRequired(approved=[], total_bytes=0, plan=()))
    p.summary([], free_before=None, free_after=None)
    out = console.export_text()
    assert "Done: 0 ok · 0 failed · 0 skipped" in out and "free space" not in out


def test_scan_progress_updates_the_spinner_text() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    with p.scanning():
        p.scan_progress(ScanStarted(providers=("a", "b", "c", "d")))
        p.scan_progress(ProviderStarted("a"))
        p.scan_progress(ProviderStarted("b"))
        assert p.status_text == "scanning… 0/4 providers · running: a, b"
        p.scan_progress(
            ProviderFinished(ProviderTiming(name="a", bytes=1, entries=1, duration_ms=1))
        )
        assert p.status_text == "scanning… 1/4 providers · running: b"


def test_control_characters_never_reach_the_console() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    evil = _entry("x\x1b]0;pwned\x07y", 10)
    p.on_event(ConfirmRequired(approved=[evil], total_bytes=10, plan=(_planned(evil),)))
    assert "\x1b" not in console.export_text()


def test_execute_step_outside_executing_updates_text_without_a_status_thread() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    uv = _entry("uv", 100)
    p.on_event(ConfirmRequired(approved=[uv], total_bytes=100, plan=(_planned(uv),)))
    p.on_event(ExecuteStep(entry=uv, action=uv.actions[0]))
    assert p._status is None
    assert p.status_text.startswith("[1/1] running:")


def test_executing_creates_a_status_that_is_gone_after_the_block() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    with p.executing():
        assert p._status is not None
    assert p._status is None
