import asyncio
import threading
from pathlib import Path

import pytest

from devdoctor.storage import build_storage
from devdoctor.types import (
    CleanupOpts,
    CommandAction,
    Entry,
    Refusal,
    RefusalKind,
    Risk,
    ShellResult,
)
from devdoctor.web.cleanup_runner import CleanupRunner
from devdoctor.web.runner_registry import RunnerRegistry
from tests.test_cleanup_async import _e, _report


@pytest.mark.asyncio
async def test_runner_drives_async_cleanup_to_completion():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))

    async def fake_run_line(_argv: tuple[str, ...]) -> ShellResult:
        return ShellResult(0, "", "")

    runner = CleanupRunner(report=rep, opts=CleanupOpts(execute=True), run_line=fake_run_line)
    task = asyncio.create_task(runner.run())

    # consume 'prompt' event, send 'y'
    ev = await runner.events.get()
    assert ev["event"] == "prompt"
    await runner.answer_prompt(entry_id="1", choice="y")

    # consume 'awaiting_confirm' event, send True
    ev = await runner.events.get()
    assert ev["event"] == "awaiting_confirm"
    await runner.answer_confirm(True)

    # consume 'execute_start', 'execute_result', 'done'
    ev = await runner.events.get()
    assert ev["event"] == "execute_start"

    ev = await runner.events.get()
    assert ev["event"] == "execute_result"
    assert ev["data"]["status"] == "ok"

    ev = await runner.events.get()
    assert ev["event"] == "done"

    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_runner_cancel_marks_remaining_skipped():
    rep = _report(
        _e("a", "1", 100, recipe=["rm /1"]),
        _e("a", "2", 200, recipe=["rm /2"]),
    )

    async def fake_run_line(_argv: tuple[str, ...]) -> ShellResult:
        return ShellResult(0, "", "")

    runner = CleanupRunner(report=rep, opts=CleanupOpts(execute=True), run_line=fake_run_line)
    task = asyncio.create_task(runner.run())

    await runner.events.get()  # prompt for entry 1
    await runner.cancel()

    # After cancel, runner emits done with partial results
    saw_done = False
    try:
        while True:
            ev = await asyncio.wait_for(runner.events.get(), timeout=1)
            if ev["event"] == "done":
                saw_done = True
                break
    except TimeoutError:
        pass
    assert saw_done
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_shared_provider_local_id_does_not_cross_route():
    """Roadmap #12 regression: two entries from DIFFERENT providers that share
    the same *provider-local* id must be independently selectable/answerable.

    discovery.scan namespaces ids to "{provider}:{id}", so a docker "images"
    entry and an ollama "images" entry become "docker:images" / "ollama:images".
    We reproduce that here and assert:

    1. Selection isolation — mirroring routes_clean's ``e.id in selected``
       filter with only the docker id selected picks the docker entry ONLY.
       Pre-fix both entries carried the bare id "images", so ``"images" in
       {"images"}`` matched both and swept ollama into the job too.
    2. Execution isolation — running the selected report cleans docker only;
       ollama's recipe never runs and never appears in the results.
    """
    # As scan produces them: globally-unique ids, same bare "images" underneath.
    docker = _e("docker", "docker:images", 100, recipe=["docker-clean"])
    ollama = _e("ollama", "ollama:images", 200, recipe=["ollama-clean"])
    rep = _report(docker, ollama)

    # routes_clean selection: user picks only the docker entry.
    selected = {"docker:images"}
    rep.entries = [e for e in rep.entries if e.id in selected]
    assert [e.provider for e in rep.entries] == ["docker"]  # ollama not swept in

    executed: list[tuple[str, ...]] = []

    async def fake_run_line(argv: tuple[str, ...]) -> ShellResult:
        executed.append(argv)
        return ShellResult(0, "", "")

    runner = CleanupRunner(report=rep, opts=CleanupOpts(execute=True), run_line=fake_run_line)
    task = asyncio.create_task(runner.run())

    ev = await runner.events.get()
    assert ev["event"] == "prompt"
    assert ev["data"]["entry_id"] == "docker:images"

    # Answering with the stale *bare* id must NOT resolve the prompt: routing
    # keys are namespaced, so a bare/foreign id can never cross-route.
    await runner.answer_prompt(entry_id="images", choice="y")
    await runner.answer_prompt(entry_id="ollama:images", choice="y")
    assert not runner._pending_prompts["docker:images"].done()

    # The correct namespaced id resolves it.
    await runner.answer_prompt(entry_id="docker:images", choice="y")

    ev = await runner.events.get()
    assert ev["event"] == "awaiting_confirm"
    await runner.answer_confirm(True)

    results = await asyncio.wait_for(task, timeout=1)

    # Only docker's recipe ran; ollama was never touched.
    assert executed == [("docker-clean",)]
    assert [r.entry_id for r in results] == ["docker:images"]


def test_registry_single_active_job():
    reg: RunnerRegistry[object] = RunnerRegistry()
    runner = reg.create(object)  # factory returns a stand-in
    assert reg.active() is runner

    # second create while active -> RuntimeError / None depending on API
    with pytest.raises(RuntimeError):
        reg.create(object)

    reg.release(runner)
    assert reg.active() is None


@pytest.mark.asyncio
async def test_runner_multi_entry_attributes_events_to_correct_entry():
    """Guards against a former bug where _current_entry got stale."""
    rep = _report(
        _e("a", "A", 100, recipe=["cmd-A"]),
        _e("a", "B", 200, recipe=["cmd-B"]),
    )

    async def fake_run_line(_argv: tuple[str, ...]) -> ShellResult:
        return ShellResult(0, "", "")

    runner = CleanupRunner(report=rep, opts=CleanupOpts(execute=True), run_line=fake_run_line)
    task = asyncio.create_task(runner.run())

    # prompt + answer for A
    ev = await runner.events.get()
    assert ev["event"] == "prompt" and ev["data"]["entry_id"] == "A"
    await runner.answer_prompt(entry_id="A", choice="y")

    # prompt + answer for B
    ev = await runner.events.get()
    assert ev["event"] == "prompt" and ev["data"]["entry_id"] == "B"
    await runner.answer_prompt(entry_id="B", choice="y")

    # confirm
    ev = await runner.events.get()
    assert ev["event"] == "awaiting_confirm"
    await runner.answer_confirm(True)

    # Collect all execute_start events and verify their entry_ids
    starts: list[str] = []
    while True:
        ev = await runner.events.get()
        if ev["event"] == "execute_start":
            starts.append(ev["data"]["entry_id"])
        if ev["event"] == "done":
            break

    # Both entries should have an execute_start event with their own id.
    assert set(starts) == {"A", "B"}
    await asyncio.wait_for(task, timeout=1)


def _worktree_owner() -> Entry:
    path = "/p/wt/feature"
    return Entry(
        provider="git-worktrees",
        id=f"git-worktrees:{path}",
        path=Path(path),
        label="app/feature · integrated",
        size_bytes=1_000,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=[],
        actions=(CommandAction(("git", "-C", "/p/app", "worktree", "remove", path)),),
    )


async def _approve_and_confirm(runner: CleanupRunner, entry_id: str) -> None:
    assert (await runner.events.get())["event"] == "prompt"
    await runner.answer_prompt(entry_id=entry_id, choice="y")
    assert (await runner.events.get())["event"] == "awaiting_confirm"
    await runner.answer_confirm(True)


async def _events_until_done(runner: CleanupRunner) -> list[dict]:
    events = [await asyncio.wait_for(runner.events.get(), timeout=5)]
    while events[-1]["event"] != "done":
        events.append(await asyncio.wait_for(runner.events.get(), timeout=5))
    return events


async def test_runner_skips_a_worktree_its_verifier_refuses():
    owner = _worktree_owner()
    loop_thread = threading.get_ident()
    verifier_threads: list[int] = []

    async def fake_run_line(_argv):
        raise AssertionError("no command may run")

    def verify(entry):
        verifier_threads.append(threading.get_ident())
        return Refusal(RefusalKind.CHANGED, "not integrated")

    runner = CleanupRunner(
        report=_report(owner), opts=CleanupOpts(execute=True), run_line=fake_run_line, verify=verify
    )
    task = asyncio.create_task(runner.run())
    await _approve_and_confirm(runner, owner.id)
    events = await _events_until_done(runner)
    results = await task

    assert len(verifier_threads) == 1
    assert verifier_threads[0] != loop_thread  # verification never blocks the event loop
    assert [r.status for r in results] == ["skipped"]
    assert [(r["status"], r["message"]) for r in events[-1]["data"]["results"]] == [
        ("skipped", "changed since the scan: not integrated; rescan before cleaning")
    ]


async def test_cancelling_while_verification_runs_never_removes_the_worktree():
    owner = _worktree_owner()
    started = threading.Event()
    release = threading.Event()
    ran: list[tuple[str, ...]] = []

    async def fake_run_line(argv):
        ran.append(argv)
        return ShellResult(0, "", "")

    def verify(entry):
        started.set()
        release.wait(timeout=5)

    runner = CleanupRunner(
        report=_report(owner), opts=CleanupOpts(execute=True), run_line=fake_run_line, verify=verify
    )
    runner._task = asyncio.create_task(runner.run())
    await _approve_and_confirm(runner, owner.id)
    assert await asyncio.to_thread(started.wait, 5)

    await runner.cancel()
    release.set()
    events = await _events_until_done(runner)
    with pytest.raises(asyncio.CancelledError):
        await runner._task

    assert ran == []
    assert "execute_start" not in [event["event"] for event in events]
    assert events[-1]["data"]["cancelled"] is True


async def test_web_audit_event_names_its_source_and_plan():
    entry = _e("a", "1", 100, recipe=["rm -rf /1"])
    rep = _report(entry)

    async def fake_run_line(_argv: tuple[str, ...]) -> ShellResult:
        return ShellResult(0, "", "")

    runner = CleanupRunner(report=rep, opts=CleanupOpts(execute=True), run_line=fake_run_line)
    task = asyncio.create_task(runner.run())
    await _approve_and_confirm(runner, entry.id)
    await _events_until_done(runner)
    results = await task
    assert [r.status for r in results] == ["ok"]

    events = build_storage().read_audit_events(limit=1)
    assert events[0]["source"] == "web"
    assert events[0]["job_id"] == runner.id
    assert [p["entry_id"] for p in events[0]["plan"]] == [entry.id]
    assert events[0]["results"][0]["provider"] == entry.provider
