from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.cleanup import build_script, run
from diskdoctor.types import CleanupOpts, Entry, Report, Risk, ShellResult
from tests.conftest import FakeShell


def _report(*entries: Entry) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
    )


def _e(provider, id_, size, risk=Risk.SAFE, recipe=None) -> Entry:
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=risk,
        recipe=recipe or [f"rm -rf /{id_}"],
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
