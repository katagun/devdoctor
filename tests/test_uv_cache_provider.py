"""The uv cache provider and the lock a parent uv process holds (#127)."""

from __future__ import annotations

from pathlib import Path

import pytest

from devdoctor.providers.tool_caches import UvCacheProvider, running_under_uv
from devdoctor.types import CommandAction, DeletePathAction, Risk, ShellResult
from tests.conftest import FakeShell


def _cache(root: Path) -> Path:
    cache = root / "uv-cache"
    (cache / "wheels").mkdir(parents=True)
    (cache / "wheels" / "pkg.whl").write_bytes(b"x" * 128)
    return cache


def _shell(cache: Path, *, uv: str | None = "/usr/local/bin/uv") -> FakeShell:
    return FakeShell(
        responses={("uv", "cache", "dir"): ShellResult(0, f"{cache}\n", "")},
        which_table={"uv": uv},
    )


def test_running_under_uv_reads_the_uv_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    # `uv run` and `uvx` export UV=<binary> to their child; an installed tool does not.
    monkeypatch.delenv("UV", raising=False)
    assert running_under_uv() is False
    monkeypatch.setenv("UV", "/Users/x/.local/bin/uv")
    assert running_under_uv() is True


def test_uses_the_active_cache_and_uv_cache_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UV", raising=False)
    cache = _cache(tmp_path)

    [entry] = UvCacheProvider(_shell(cache)).discover()

    assert entry.provider == "uv-cache"
    assert entry.id == str(cache)
    assert entry.path == cache
    assert entry.risk is Risk.SAFE
    assert entry.reclaimable_bytes == entry.footprint_bytes
    assert entry.actions == (CommandAction(("uv", "cache", "clean")),)


def test_under_uv_the_cleanup_forces_past_the_parent_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The parent `uv run` holds the cache lock until devdoctor exits, so a plain
    # `uv cache clean` from inside waits for it forever (#127).
    monkeypatch.setenv("UV", "/Users/x/.local/bin/uv")
    cache = _cache(tmp_path)

    provider = UvCacheProvider(_shell(cache))
    [entry] = provider.discover()

    assert entry.actions == (CommandAction(("uv", "cache", "clean", "--force")),)
    assert any("holds the uv cache lock" in note for note in provider.diagnostics)


def test_without_uv_on_path_the_default_directory_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    cache = home / ".cache" / "uv"
    cache.mkdir(parents=True)
    (cache / "blob").write_bytes(b"x" * 64)
    shell = FakeShell(which_table={"uv": None})

    [entry] = UvCacheProvider(shell).discover()

    assert entry.path == cache
    assert entry.actions == (DeletePathAction(cache),)
    assert shell.calls == []


def test_uv_cache_dir_env_wins_when_uv_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UV", raising=False)
    cache = _cache(tmp_path)
    monkeypatch.setenv("UV_CACHE_DIR", str(cache))

    [entry] = UvCacheProvider(FakeShell(which_table={"uv": None})).discover()

    assert entry.path == cache


def test_a_failing_uv_cache_dir_falls_back_to_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    cache = tmp_path / "xdg-cache" / "uv"
    cache.mkdir(parents=True)
    (cache / "blob").write_bytes(b"x" * 64)
    shell = FakeShell(
        responses={("uv", "cache", "dir"): ShellResult(1, "", "boom")},
        which_table={"uv": "/usr/local/bin/uv"},
    )

    [entry] = UvCacheProvider(shell).discover()

    assert entry.path == cache
    assert entry.actions == (CommandAction(("uv", "cache", "clean")),)


def test_no_cache_directory_means_no_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UV", raising=False)
    missing = tmp_path / "nowhere"

    assert UvCacheProvider(_shell(missing)).discover() == []
