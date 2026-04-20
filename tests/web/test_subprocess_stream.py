import pytest

from diskdoctor.types import ShellResult
from diskdoctor.web.subprocess_stream import run_line_streaming


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
