from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.cleanup import run
from diskdoctor.types import CleanupOpts, Entry, Report, Risk
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
