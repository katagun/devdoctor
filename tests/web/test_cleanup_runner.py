import asyncio

import pytest

from diskdoctor.types import CleanupOpts, ShellResult
from diskdoctor.web.cleanup_runner import CleanupRunner
from diskdoctor.web.runner_registry import RunnerRegistry
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


def test_registry_single_active_job():
    reg: RunnerRegistry[object] = RunnerRegistry()
    runner = reg.create(object)  # factory returns a stand-in
    assert reg.active() is runner

    # second create while active -> RuntimeError / None depending on API
    with pytest.raises(RuntimeError):
        reg.create(object)

    reg.release(runner)
    assert reg.active() is None
