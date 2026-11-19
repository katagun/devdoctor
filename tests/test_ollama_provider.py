from devdoctor.providers.ollama import OllamaProvider
from devdoctor.types import Risk, ShellResult
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
    (
        home
        / ".ollama"
        / "models"
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "llama3"
        / "8b"
    ).mkdir(parents=True)
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


def test_discover_enriches_entries_with_manifest_stat(tmp_path, monkeypatch):
    """Each `ollama list` row should pick up real mtime/owner/perms from the
    on-disk manifest file. Without this enrichment the scan table shows blank
    age/ownership/permissions for every model — `ollama list` doesn't surface
    those fields itself.
    """
    home = tmp_path / "h"
    manifest = (
        home
        / ".ollama"
        / "models"
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "llama3"
        / "8b"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"schemaVersion": 2}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    list_out = (
        "NAME                    ID              SIZE      MODIFIED\n"
        "llama3:8b               365c0bd3c000    4.7 GB    2 weeks ago\n"
    )
    sh = FakeShell(
        which_table={"ollama": "/x"},
        responses={("ollama", "list"): ShellResult(0, list_out, "")},
    )
    [e] = OllamaProvider(sh).discover()
    assert e.path == manifest
    assert e.mtime is not None
    # Stat fields populated from the manifest file:
    assert e.owner is not None
    assert e.perms is not None and e.perms.startswith("-")  # regular file


def test_discover_leaves_path_none_when_manifest_missing(tmp_path, monkeypatch):
    """Cloud-only or custom-registry models may not have a local manifest;
    enrichment must fail silently and still produce a usable Entry."""
    monkeypatch.setenv("HOME", str(tmp_path / "no-such-home"))
    monkeypatch.setattr("sys.platform", "darwin")
    list_out = (
        "NAME                ID              SIZE      MODIFIED\n"
        "phantom:latest      000             1.0 GB    just now\n"
    )
    sh = FakeShell(
        which_table={"ollama": "/x"},
        responses={("ollama", "list"): ShellResult(0, list_out, "")},
    )
    [e] = OllamaProvider(sh).discover()
    assert e.path is None
    assert e.mtime is None
    assert e.owner is None


def test_discover_shell_quotes_suspicious_model_names(monkeypatch):
    """Guard against command injection via a malicious model tag."""
    monkeypatch.setattr("sys.platform", "darwin")
    malicious_list = (
        "NAME                    ID              SIZE      MODIFIED\n"
        "a; rm -rf /               abc123          1.0 GB    just now\n"
    )
    sh = FakeShell(
        which_table={"ollama": "/x"},
        responses={("ollama", "list"): ShellResult(0, malicious_list, "")},
    )
    [e] = OllamaProvider(sh).discover()
    # The semicolon must be quoted, not left bare.
    assert "rm -rf /" not in e.recipe[0] or "'" in e.recipe[0]


def test_the_models_directory_follows_ollama_models(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    moved = tmp_path / "external" / "ollama-models"
    (moved / "blobs").mkdir(parents=True)
    (moved / "blobs" / "sha256-aa").write_bytes(b"x" * 4096)
    monkeypatch.setenv("OLLAMA_MODELS", str(moved))
    shell = FakeShell(
        which_table={"ollama": "/opt/homebrew/bin/ollama"},
        responses={("ollama", "list"): ShellResult(1, "", "could not connect")},
    )

    (entry,) = OllamaProvider(shell).discover()

    assert entry.path == moved and entry.size_bytes >= 4096


def test_a_hung_ollama_falls_back_to_the_models_directory(tmp_path, monkeypatch):
    import subprocess

    home = tmp_path / "home"
    (home / ".ollama" / "models" / "blobs").mkdir(parents=True)
    (home / ".ollama" / "models" / "blobs" / "sha256-aa").write_bytes(b"x" * 4096)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    timeouts = []

    class Hung(FakeShell):
        def run(self, argv, *, check=False, timeout=None, env=None):
            timeouts.append(timeout)
            raise subprocess.TimeoutExpired(argv, timeout or 0)

    (entry,) = OllamaProvider(Hung(which_table={"ollama": "/x/ollama"})).discover()

    assert entry.path == home / ".ollama" / "models"
    assert timeouts and timeouts[0] is not None
