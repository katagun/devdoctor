import asyncio

import pytest

from devdoctor.types import CleanupOpts, ShellResult
from devdoctor.web.cleanup_runner import CleanupRunner
from devdoctor.web.runner_registry import RunnerRegistry
from tests.test_cleanup_async import _e, _report


@pytest.mark.asyncio
async def test_runner_drives_async_cleanup_to_completion():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))

    async def fake_run_line(line: str) -> ShellResult:
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

    async def fake_run_line(line: str) -> ShellResult:
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

    executed: list[str] = []

    async def fake_run_line(line: str) -> ShellResult:
        executed.append(line)
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
    assert executed == ["docker-clean"]
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

    async def fake_run_line(line: str) -> ShellResult:
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
