from pathlib import Path

from diskdoctor.providers.huggingface import HuggingFaceProvider
from diskdoctor.types import Risk
from tests.conftest import FakeShell


def _mk_hf_repo(hub_root: Path, kind: str, org: str, name: str, *, blob_size: int) -> Path:
    repo = hub_root / f"{kind}--{org}--{name}"
    (repo / "blobs").mkdir(parents=True)
    (repo / "snapshots" / "abc123").mkdir(parents=True)
    blob = repo / "blobs" / "sha256-deadbeef"
    blob.write_bytes(b"x" * blob_size)
    # snapshots contain symlinks to blobs (HF cache convention)
    (repo / "snapshots" / "abc123" / "file.bin").symlink_to(blob)
    return repo


def test_discover_emits_one_entry_per_repo(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    hub = home / ".cache" / "huggingface" / "hub"
    _mk_hf_repo(hub, "models", "bert-base-uncased", "main", blob_size=1000)
    _mk_hf_repo(hub, "datasets", "princeton-nlp", "SWE-bench", blob_size=2000)

    entries = HuggingFaceProvider(FakeShell()).discover()
    assert len(entries) == 2
    ids = {e.id for e in entries}
    assert any("bert-base-uncased" in i for i in ids)
    assert any("SWE-bench" in i for i in ids)


def test_size_does_not_double_count_symlinked_blobs(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    hub = home / ".cache" / "huggingface" / "hub"
    _mk_hf_repo(hub, "models", "a", "b", blob_size=1000)
    [e] = HuggingFaceProvider(FakeShell()).discover()
    # Blob is 1000 B; snapshot symlink points to it. Total should be ~1000,
    # not 2000, because we don't follow symlinks.
    assert e.size_bytes < 1500


def test_risk_is_reclaimable(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    hub = home / ".cache" / "huggingface" / "hub"
    _mk_hf_repo(hub, "models", "a", "b", blob_size=100)
    [e] = HuggingFaceProvider(FakeShell()).discover()
    assert e.risk == Risk.RECLAIMABLE


def test_discover_empty_when_hub_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "darwin")
    assert HuggingFaceProvider(FakeShell()).discover() == []
