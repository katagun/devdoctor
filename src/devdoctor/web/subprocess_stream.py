from __future__ import annotations

import asyncio
import shlex
from collections.abc import Awaitable, Callable

from devdoctor.types import ShellResult

OnChunk = Callable[[str, str], Awaitable[None]]


async def run_line_streaming(
    line: str,
    *,
    on_chunk: OnChunk,
    timeout: float | None = None,
) -> ShellResult:
    """Execute a shell-quoted command line asynchronously.

    Yields stdout/stderr lines as they arrive via `on_chunk(stream, text)`.
    Returns the aggregate ShellResult once the process exits. Does not raise
    on non-zero exit — returns the result for the caller to inspect.

    `line` is split with shlex (same as the sync CLI path) and passed to
    asyncio.create_subprocess_exec; no shell is invoked.
    """
    argv = shlex.split(line)
    return await run_argv_streaming(tuple(argv), on_chunk=on_chunk, timeout=timeout)


async def run_argv_streaming(
    argv: tuple[str, ...],
    *,
    on_chunk: OnChunk,
    timeout: float | None = None,
) -> ShellResult:
    """Execute structured argv asynchronously without shell parsing."""
    if not argv:
        return ShellResult(returncode=1, stdout="", stderr="empty command")

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        return ShellResult(returncode=127, stdout="", stderr=str(exc))
    except OSError as exc:
        return ShellResult(returncode=1, stdout="", stderr=str(exc))

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    async def _pump(reader: asyncio.StreamReader, stream_name: str, sink: list[str]) -> None:
        assert reader is not None
        while True:
            line_bytes = await reader.readline()
            if not line_bytes:
                break
            text = line_bytes.decode("utf-8", errors="replace")
            sink.append(text)
            await on_chunk(stream_name, text)

    timed_out = False
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_pump(proc.stdout, "stdout", stdout_chunks))  # type: ignore[arg-type]
            tg.create_task(_pump(proc.stderr, "stderr", stderr_chunks))  # type: ignore[arg-type]
            # Caught inside the group: an error that leaves its body comes out
            # wrapped in an ExceptionGroup, which `except TimeoutError` misses.
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except TimeoutError:
                timed_out = True
                await _stop(proc)
    finally:
        # Cancellation (job cancelled, client gone) or a failed pump: the command
        # must not outlive the job that reports it stopped.
        if proc.returncode is None:
            await _stop(proc)

    if timed_out:
        return ShellResult(
            returncode=proc.returncode or 124,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks) + f"\ntimed out after {timeout}s",
        )

    return ShellResult(
        returncode=proc.returncode or 0,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


_TERMINATE_GRACE_S = 5.0


async def _stop(proc: asyncio.subprocess.Process) -> None:
    """Terminate ``proc``, kill it if it ignores that, and reap it."""
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
