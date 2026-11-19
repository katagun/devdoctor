import pytest

from devdoctor.types import ShellResult
from devdoctor.web.subprocess_stream import run_line_streaming


@pytest.mark.asyncio
async def test_success_yields_stdout_and_zero_exit():
    chunks: list[tuple[str, str]] = []

    async def on_chunk(stream: str, text: str) -> None:
        chunks.append((stream, text))

    result = await run_line_streaming("sh -c 'echo hello'", on_chunk=on_chunk)
    assert isinstance(result, ShellResult)
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert any(s == "stdout" and "hello" in c for s, c in chunks)


@pytest.mark.asyncio
async def test_stderr_and_nonzero_exit():
    chunks: list[tuple[str, str]] = []

    async def on_chunk(stream: str, text: str) -> None:
        chunks.append((stream, text))

    result = await run_line_streaming("sh -c 'echo oops >&2; exit 2'", on_chunk=on_chunk)
    assert result.returncode == 2
    assert "oops" in result.stderr
    assert any(s == "stderr" for s, _ in chunks)


@pytest.mark.asyncio
async def test_missing_binary_returns_nonzero_result_not_exception():
    async def on_chunk(_s: str, _t: str) -> None:
        pass

    result = await run_line_streaming("definitely-not-a-binary-xyz", on_chunk=on_chunk)
    assert result.returncode != 0
    # The exact error goes into stderr; the message is platform-specific.
    assert result.stderr  # non-empty


def _alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


_PRINT_PID_THEN_SLEEP = "import os, time; print(os.getpid(), flush=True); time.sleep(60)"


async def test_cancelling_the_run_stops_the_command():
    """A cancelled cleanup job must not leave its `rm -rf` running behind it."""
    import asyncio
    import sys

    started: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def on_chunk(_stream: str, text: str) -> None:
        if not started.done():
            started.set_result(int(text))

    from devdoctor.web.subprocess_stream import run_argv_streaming

    task = asyncio.create_task(
        run_argv_streaming((sys.executable, "-c", _PRINT_PID_THEN_SLEEP), on_chunk=on_chunk)
    )
    pid = await asyncio.wait_for(started, timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not _alive(pid)


async def test_a_timeout_stops_the_command_and_reports_it():
    import sys

    pids: list[int] = []

    async def on_chunk(_stream: str, text: str) -> None:
        pids.append(int(text))

    from devdoctor.web.subprocess_stream import run_argv_streaming

    result = await run_argv_streaming(
        (sys.executable, "-c", _PRINT_PID_THEN_SLEEP), on_chunk=on_chunk, timeout=1.0
    )
    assert result.returncode != 0
    assert "timed out" in result.stderr
    assert pids and not _alive(pids[0])
