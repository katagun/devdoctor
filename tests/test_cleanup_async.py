from datetime import UTC, datetime
from pathlib import Path

import pytest

from diskdoctor.cleanup import run_async
from diskdoctor.types import CleanupOpts, Entry, Report, Risk, ShellResult


def _report(*entries: Entry) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
    )


def _e(provider, id_, size, recipe=None):
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=recipe or [f"rm -rf /{id_}"],
    )


def _scripted(values):
    async def _f(_x):
        return values.pop(0)

    return _f


@pytest.mark.asyncio
async def test_run_async_drives_generator_to_completion():
    rep = _report(_e("a", "1", 100, recipe=["rm /1"]))
    executed: list[str] = []

    async def run_line(line: str) -> ShellResult:
        executed.append(line)
        return ShellResult(0, "", "")

    results = await run_async(
        rep,
        run_line=run_line,
        prompt_choice=_scripted(["y"]),
        confirm=_scripted([True]),
        opts=CleanupOpts(execute=True),
    )
    assert executed == ["rm /1"]
    assert [(r.status, r.freed_bytes) for r in results] == [("ok", 100)]


@pytest.mark.asyncio
async def test_run_async_preview_no_calls():
    rep = _report(_e("a", "1", 100))
    calls = {"prompt": 0, "confirm": 0, "run": 0}

    async def never_prompt(_):
        calls["prompt"] += 1
        raise AssertionError("must not be called")

    async def never_confirm(_):
        calls["confirm"] += 1
        raise AssertionError("must not be called")

    async def never_run(_):
        calls["run"] += 1
        raise AssertionError("must not be called")

    results = await run_async(
        rep,
        run_line=never_run,
        prompt_choice=never_prompt,
        confirm=never_confirm,
        opts=CleanupOpts(execute=False),
    )
    assert [r.status for r in results] == ["dry_run"]
    assert calls == {"prompt": 0, "confirm": 0, "run": 0}
