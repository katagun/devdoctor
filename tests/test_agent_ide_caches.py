"""AI agent and IDE caches (#83): downloads and logs are safe, extensions are advice."""

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
        ("vscode-extension-downloads", "desktop-apps", Risk.SAFE),
        ("cursor-extension-downloads", "desktop-apps", Risk.SAFE),
        ("cursor-updater-cache", "desktop-apps", Risk.SAFE),
        ("vscode-logs", "desktop-apps", Risk.SAFE),
        ("cursor-logs", "desktop-apps", Risk.SAFE),
        ("editor-extensions", "desktop-apps", Risk.RECLAIMABLE),
        ("codex-runtimes-cache", "agents", Risk.RECLAIMABLE),
        ("exo-models", "local-ai", Risk.RECLAIMABLE),
    ],
)
def test_catalogue_names_family_and_risk(name: str, family: str, risk: Risk) -> None:
    provider = _provider(name)
    assert (provider.family, provider.risk) == (family, risk)


def test_downloads_logs_and_models_are_plain_deletions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    expected = {
        "vscode-extension-downloads": "Library/Application Support/Code/CachedExtensionVSIXs",
        "cursor-logs": "Library/Application Support/Cursor/logs",
        "codex-runtimes-cache": ".cache/codex-runtimes",
        "exo-models": ".exo/models",
    }
    for rel in expected.values():
        _payload(home / rel)

    for name, rel in expected.items():
        [entry] = _provider(name).discover()
        assert entry.path == home / rel
        assert entry.actions == (DeletePathAction(home / rel),)
        assert entry.reclaimable_bytes == entry.footprint_bytes


def test_installed_editor_extensions_are_advice_per_editor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Extensions are the user's editor setup: sized and shown, uninstalled only
    # through the editor, never removed by DevDoctor.
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    for editor in (".vscode", ".cursor", ".windsurf"):
        _payload(home / editor / "extensions" / "publisher.ext-1.0.0")

    entries = sorted(_provider("editor-extensions").discover(), key=lambda e: str(e.path))

    assert [e.path for e in entries] == [
        home / ".cursor" / "extensions",
        home / ".vscode" / "extensions",
        home / ".windsurf" / "extensions",
    ]
    for entry in entries:
        assert entry.reclaimable_bytes is None
        assert all(isinstance(action, AdviceAction) for action in entry.actions)
        assert "--uninstall-extension" in " ".join(a.message for a in entry.actions)
