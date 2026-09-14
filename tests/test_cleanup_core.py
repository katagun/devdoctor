from datetime import UTC, datetime
from pathlib import Path

from devdoctor.cleanup import (
    ConfirmRequired,
    EntryResolved,
    ExecuteStep,
    PromptRequired,
    iter_cleanup_events,
)
from devdoctor.types import (
    CleanResult,
    CleanupOpts,
    CommandAction,
    DeletePathAction,
    Entry,
    Report,
    Risk,
    ShellResult,
)


def _report(*entries: Entry) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
    )


def _e(
    provider: str, id_: str, size: int, risk: Risk = Risk.SAFE, recipe: list[str] | None = None
) -> Entry:
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


def _drive(gen, answers: list):
    """Drive a cleanup generator. `answers` maps to each yield point
    (PromptRequired/ConfirmRequired/ExecuteStep) in order.
    """
    out_events = []
    resolved = []
    try:
        event = next(gen)
        for answer in answers:
            out_events.append(event)
            if isinstance(event, EntryResolved):
                resolved.append(event.result)
                event = next(gen)
                if answer is not None:
                    # caller expected to answer but generator advanced past — bug
                    raise AssertionError("unexpected EntryResolved without answer slot")
                continue
            event = gen.send(answer)
        # drain any trailing EntryResolved
        while True:
            out_events.append(event)
            if isinstance(event, EntryResolved):
                resolved.append(event.result)
            event = next(gen)
    except StopIteration:
        pass
    return out_events, resolved


def test_preview_yields_only_dry_run_results():
    report = _report(_e("a", "1", 100), _e("b", "1", 200))
    events, results = _drive(iter_cleanup_events(report, CleanupOpts(execute=False)), [None, None])
    assert all(isinstance(e, EntryResolved) for e in events)
    assert [r.status for r in results] == ["dry_run", "dry_run"]


def test_execute_yes_path_yields_prompt_confirm_execute_resolved():
    report = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    gen = iter_cleanup_events(report, CleanupOpts(execute=True))

    ev = next(gen)
    assert isinstance(ev, PromptRequired)
    assert ev.entry.id == "1"

    ev = gen.send("y")
    assert isinstance(ev, ConfirmRequired)
    assert len(ev.approved) == 1
    assert ev.total_bytes == 100

    ev = gen.send(True)
    assert isinstance(ev, ExecuteStep)
    assert ev.line == "rm -rf /1"

    ev = gen.send(ShellResult(returncode=0, stdout="", stderr=""))
    assert isinstance(ev, EntryResolved)
    assert ev.result.status == "ok"
    assert ev.result.freed_bytes == 100


def test_execute_n_yields_no_execute_for_that_entry():
    report = _report(_e("a", "1", 100), _e("a", "2", 200))
    gen = iter_cleanup_events(report, CleanupOpts(execute=True))
    # entry 1: n
    assert isinstance(next(gen), PromptRequired)
    ev = gen.send("n")
    # entry 2: y
    assert isinstance(ev, PromptRequired)
    ev = gen.send("y")
    # final confirm (only 1 approved)
    assert isinstance(ev, ConfirmRequired)
    assert [e.id for e in ev.approved] == ["2"]
    ev = gen.send(True)
    # Execute phase emits resolutions in selection order. Entry 1 (skipped)
    # resolves first as EntryResolved; entry 2 then yields ExecuteStep.
    statuses: list[tuple[str, str]] = []
    saw_execute_for_entry_2 = False
    while True:
        try:
            if isinstance(ev, EntryResolved):
                statuses.append((ev.result.entry_id, ev.result.status))
                ev = next(gen)
            elif isinstance(ev, ExecuteStep):
                assert ev.entry.id == "2"
                saw_execute_for_entry_2 = True
                ev = gen.send(ShellResult(0, "", ""))
            else:
                raise AssertionError(f"unexpected event: {ev!r}")
        except StopIteration:
            break
    assert saw_execute_for_entry_2
    assert ("1", "skipped") in statuses
    assert ("2", "ok") in statuses


def test_dangerous_gated_skipped_with_message():
    report = _report(_e("a", "1", 100, Risk.DANGEROUS))
    gen = iter_cleanup_events(report, CleanupOpts(execute=True, allow_dangerous=False))
    ev = next(gen)
    assert isinstance(ev, EntryResolved)
    assert ev.result.status == "skipped"
    assert "dangerous" in (ev.result.message or "").lower()


def test_yes_safe_skips_prompt_for_safe_only():
    report = _report(
        _e("a", "1", 100, Risk.SAFE, recipe=["rm /1"]),
        _e("a", "2", 200, Risk.RECLAIMABLE, recipe=["rm /2"]),
    )
    gen = iter_cleanup_events(report, CleanupOpts(execute=True, yes_safe=True))
    # entry 1 is SAFE + yes_safe -> no prompt; next yield should be for entry 2
    ev = next(gen)
    assert isinstance(ev, PromptRequired)
    assert ev.entry.id == "2"
    ev = gen.send("y")
    # confirm
    assert isinstance(ev, ConfirmRequired)
    assert [e.id for e in ev.approved] == ["1", "2"]


def test_quit_skips_remaining():
    report = _report(_e("a", "1", 100), _e("a", "2", 200), _e("a", "3", 50))
    gen = iter_cleanup_events(report, CleanupOpts(execute=True))
    assert isinstance(next(gen), PromptRequired)
    ev = gen.send("q")
    # After q, no more prompts — generator proceeds to resolve everything skipped.
    resolved = []
    while True:
        try:
            if isinstance(ev, EntryResolved):
                resolved.append(ev.result)
            ev = next(gen)
        except StopIteration:
            break
    assert [r.status for r in resolved] == ["skipped", "skipped", "skipped"]


def test_execute_shell_failure_marks_error():
    report = _report(_e("a", "1", 100, recipe=["rm /1"]))
    gen = iter_cleanup_events(report, CleanupOpts(execute=True))
    next(gen)  # PromptRequired
    gen.send("y")  # -> ConfirmRequired
    ev = gen.send(True)  # -> ExecuteStep
    ev = gen.send(ShellResult(1, "", "boom"))  # -> EntryResolved
    assert isinstance(ev, EntryResolved)
    assert ev.result.status == "error"
    assert "boom" in (ev.result.message or "")


def test_final_confirm_no_marks_everything_aborted():
    report = _report(_e("a", "1", 100))
    gen = iter_cleanup_events(report, CleanupOpts(execute=True))
    next(gen)  # PromptRequired
    gen.send("y")  # -> ConfirmRequired
    ev = gen.send(False)  # user declines
    assert isinstance(ev, EntryResolved)
    assert ev.result.status == "skipped"
    assert "aborted" in (ev.result.message or "").lower()


_WORKTREE = Path("/p/wt/feature")


def _worktree_owner() -> Entry:
    return Entry(
        provider="git-worktrees",
        id="git-worktrees:/p/wt/feature",
        path=_WORKTREE,
        label="app/feature · integrated",
        size_bytes=1_000,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=[],
        actions=(CommandAction(("git", "-C", "/p/app", "worktree", "remove", str(_WORKTREE))),),
    )


def _content(id_: str, path: Path) -> Entry:
    return Entry(
        provider="node-project-dependencies",
        id=id_,
        path=path,
        label=str(path),
        size_bytes=600,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=[],
        actions=(DeletePathAction(path),),
    )


def _run_cleanup(report: Report, choices: dict[str, str], returncodes: dict[str, int]):
    """Drive a cleanup: answer prompts by entry id, confirm, record executed entry ids."""
    executed: list[str] = []
    results = {}
    gen = iter_cleanup_events(report, CleanupOpts(execute=True))
    try:
        event = next(gen)
        while True:
            if isinstance(event, PromptRequired):
                event = gen.send(choices[event.entry.id])
            elif isinstance(event, ConfirmRequired):
                event = gen.send(True)
            elif isinstance(event, ExecuteStep):
                executed.append(event.entry.id)
                event = gen.send(ShellResult(returncodes.get(event.entry.id, 0), "", "refused"))
            else:
                results[event.result.entry_id] = event.result
                event = next(gen)
    except StopIteration:
        pass
    return executed, results


def _worktree_report() -> tuple[Report, Entry, Entry, Entry]:
    inside = _content("node:inside", _WORKTREE / "node_modules")
    owner = _worktree_owner()
    outside = _content("node:outside", Path("/p/app/node_modules"))
    return _report(inside, owner, outside), inside, owner, outside


def test_contents_of_a_removed_worktree_are_skipped_after_it_runs_first():
    report, inside, owner, outside = _worktree_report()

    executed, results = _run_cleanup(report, dict.fromkeys(_ids(report), "y"), {})

    assert executed == [owner.id, outside.id]
    assert results[owner.id].status == "ok"
    assert results[inside.id] == CleanResult(
        entry_id=inside.id,
        status="skipped",
        freed_bytes=0,
        message="removed with worktree app/feature · integrated",
    )
    assert results[outside.id].status == "ok"
    assert set(results) == set(_ids(report))


def test_contents_run_when_the_worktree_removal_fails():
    report, inside, owner, outside = _worktree_report()

    executed, results = _run_cleanup(report, dict.fromkeys(_ids(report), "y"), {owner.id: 128})

    assert executed == [owner.id, inside.id, outside.id]
    assert results[owner.id].status == "error"
    assert results[inside.id].status == "ok"
    assert set(results) == set(_ids(report))


def test_contents_run_when_the_worktree_is_declined():
    report, inside, owner, outside = _worktree_report()
    choices = {inside.id: "y", owner.id: "n", outside.id: "y"}

    executed, results = _run_cleanup(report, choices, {})

    assert executed == [inside.id, outside.id]
    assert results[owner.id].message == "declined"
    assert results[inside.id].status == "ok"
    assert set(results) == set(_ids(report))


def _ids(report: Report) -> list[str]:
    return [entry.id for entry in report.entries]
