from pathlib import Path

from diskdoctor.providers.ollama import OllamaProvider
from diskdoctor.types import Risk, ShellResult
from tests.conftest import FakeShell


_OLLAMA_LIST_OUT = (
    "NAME                    ID              SIZE      MODIFIED\n"
    "llama3:8b               365c0bd3c000    4.7 GB    2 weeks ago\n"
    "qwen2:7b                8c6f08f5f5c6    4.4 GB    3 days ago\n"
)


def test_discover_parses_ollama_list(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"ollama": "/opt/homebrew/bin/ollama"},
        responses={("ollama", "list"): ShellResult(0, _OLLAMA_LIST_OUT, "")},
    )
    p = OllamaProvider(sh)
    entries = p.discover()
    assert {e.id for e in entries} == {"llama3:8b", "qwen2:7b"}
    llama = next(e for e in entries if e.id == "llama3:8b")
    # 4.7 GB → about 5e9 bytes
    assert 4_000_000_000 < llama.size_bytes < 6_000_000_000
    assert llama.recipe == ["ollama rm llama3:8b"]
    assert llama.risk == Risk.RECLAIMABLE


def test_discover_falls_back_to_walking_when_list_fails(tmp_path, monkeypatch):
    # Arrange: fake HOME with a models dir
    home = tmp_path / "h"
    (home / ".ollama" / "models" / "manifests" / "registry.ollama.ai" / "library" / "llama3" / "8b").mkdir(parents=True)
    blob = home / ".ollama" / "models" / "blobs"
    blob.mkdir(parents=True)
    (blob / "sha256-aaaa").write_bytes(b"x" * 4_000_000)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    sh = FakeShell(
        which_table={"ollama": "/opt/homebrew/bin/ollama"},
        responses={("ollama", "list"): ShellResult(1, "", "daemon not running")},
    )
    p = OllamaProvider(sh)
    entries = p.discover()
    # Fallback emits at least one entry representing the models directory.
    assert len(entries) >= 1
    assert all(e.risk == Risk.RECLAIMABLE for e in entries)
    # Recipes are rm -rf when falling back to paths.
    assert all(e.recipe[0].startswith("rm -rf ") for e in entries)


def test_available_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(which_table={"ollama": None})
    assert OllamaProvider(sh).available() is False
