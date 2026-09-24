"""The tail of developer caches from #88: safe deletions and per-version advice."""

from __future__ import annotations

from pathlib import Path

import pytest

from devdoctor.registry import load_providers
from devdoctor.types import AdviceAction, DeletePathAction, Risk
from tests.conftest import FakeShell


def _provider(name: str):
    return next(p for p in load_providers(FakeShell()) if p.name == name)


def _payload(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "blob").write_bytes(b"x" * 512)


@pytest.mark.parametrize(
    ("name", "family", "risk"),
    [
        ("pre-commit-cache", "python", Risk.SAFE),
        ("puppeteer-browsers", "javascript", Risk.SAFE),
        ("node-gyp-cache", "javascript", Risk.SAFE),
        ("electron-cache", "javascript", Risk.SAFE),
        ("opam-download-cache", "ocaml", Risk.SAFE),
        ("google-updater-cache", "desktop-apps", Risk.SAFE),
        ("docling-cache", "local-ai", Risk.RECLAIMABLE),
        ("rustup-toolchains", "rust", Risk.RECLAIMABLE),
        ("nvm-node-versions", "javascript", Risk.RECLAIMABLE),
        ("pyenv-versions", "python", Risk.RECLAIMABLE),
        ("vagrant-boxes", "containers", Risk.RECLAIMABLE),
        ("steampipe-plugins", "infra", Risk.RECLAIMABLE),
    ],
)
def test_catalogue_names_family_and_risk(name: str, family: str, risk: Risk) -> None:
    provider = _provider(name)
    assert (provider.family, provider.risk) == (family, risk)


def test_caches_are_plain_deletions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    for rel in ("cache/pre-commit", "cache/puppeteer", "cache/docling"):
        _payload(home / ("." + rel))

    for name, rel in (
        ("pre-commit-cache", ".cache/pre-commit"),
        ("puppeteer-browsers", ".cache/puppeteer"),
        ("docling-cache", ".cache/docling"),
    ):
        [entry] = _provider(name).discover()
        assert entry.path == home / rel
        assert entry.actions == (DeletePathAction(home / rel),)
        assert entry.reclaimable_bytes == entry.footprint_bytes


def test_installed_versions_are_one_advice_entry_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A toolchain, node or python version may be the one in use, and its tool
    # keeps an index that a bare rm leaves stale: the entry names the tool's own
    # uninstall command and is never deleted by DevDoctor.
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    layouts = {
        "rustup-toolchains": (".rustup/toolchains", ["stable-aarch64-apple-darwin", "nightly"]),
        "nvm-node-versions": (".nvm/versions/node", ["v20.12.2", "v22.19.0", "v24.13.1"]),
        "pyenv-versions": (".pyenv/versions", ["3.11.8"]),
    }
    for base, versions in layouts.values():
        for version in versions:
            _payload(home / base / version)
    (home / ".rustup" / "toolchains" / "not-a-dir").write_bytes(b"x")

    for name, (_base, versions) in layouts.items():
        entries = _provider(name).discover()
        assert sorted(e.path.name for e in entries if e.path) == sorted(
            versions + (["not-a-dir"] if name == "rustup-toolchains" else [])
        )
        for entry in entries:
            assert entry.risk is Risk.RECLAIMABLE
            assert entry.reclaimable_bytes is None
            assert all(isinstance(action, AdviceAction) for action in entry.actions)
            assert "uninstall" in " ".join(a.message for a in entry.actions)


def test_vagrant_and_steampipe_point_at_their_own_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _payload(home / ".vagrant.d" / "boxes" / "centos-VAGRANTSLASH-7")
    _payload(home / ".steampipe" / "plugins" / "hub.steampipe.io")

    [boxes] = _provider("vagrant-boxes").discover()
    [plugins] = _provider("steampipe-plugins").discover()

    assert boxes.path == home / ".vagrant.d" / "boxes"
    assert "vagrant box prune" in " ".join(a.message for a in boxes.actions)
    assert plugins.path == home / ".steampipe" / "plugins"
    assert "steampipe plugin uninstall" in " ".join(a.message for a in plugins.actions)
    for entry in (boxes, plugins):
        assert entry.reclaimable_bytes is None
