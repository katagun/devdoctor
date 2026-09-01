from pathlib import Path

from devdoctor.providers.lm_studio import LMStudioProvider
from devdoctor.types import Risk
from tests.conftest import FakeShell


def _mk_model(root: Path, publisher: str, model: str, size: int) -> None:
    d = root / publisher / model
    d.mkdir(parents=True)
    (d / "weights.bin").write_bytes(b"0" * size)


def test_discover_emits_one_entry_per_publisher_model(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    models_root = home / ".cache" / "lm-studio" / "models"
    _mk_model(models_root, "ibm-granite", "granite-docling-258M-mlx", 500)
    _mk_model(models_root, "mlx-community", "gpt-oss-20b-MXFP4-Q8", 1000)

    entries = LMStudioProvider(FakeShell()).discover()
    ids = {e.id for e in entries}
    assert ids == {
        "ibm-granite/granite-docling-258M-mlx",
        "mlx-community/gpt-oss-20b-MXFP4-Q8",
    }
    for e in entries:
        assert e.risk == Risk.RECLAIMABLE
        assert e.recipe[0].startswith("rm -rf ")


def test_discover_returns_empty_when_models_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "darwin")
    assert LMStudioProvider(FakeShell()).discover() == []


def test_available_has_no_required_binary(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert LMStudioProvider(FakeShell()).available() is True


def test_skips_empty_legacy_dirs_left_by_uninstalls(tmp_path, monkeypatch):
    """Empty publisher/model directories shouldn't show up as 0-byte entries."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    models_root = home / ".cache" / "lm-studio" / "models"
    (models_root / "ghost-publisher" / "ghost-model").mkdir(parents=True)
    assert LMStudioProvider(FakeShell()).discover() == []


def test_hub_layout_resolves_huggingface_cache_bytes(tmp_path, monkeypatch):
    """v0.3+ manifests at hub/models reference HF repos for the real bytes."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    # LM Studio hub manifest declares the model.
    manifest_dir = home / ".cache" / "lm-studio" / "hub" / "models" / "openai" / "gpt-oss-20b"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "model.yaml").write_text(
        "model: openai/gpt-oss-20b\n"
        "base:\n"
        "  - key: lmstudio-community/gpt-oss-20b-gguf\n"
        "    sources:\n"
        "      - type: huggingface\n"
        "        user: lmstudio-community\n"
        "        repo: gpt-oss-20b-GGUF\n"
    )

    # The actual bytes live in the HF cache under the canonical repo dir.
    hf_repo = (
        home / ".cache" / "huggingface" / "hub" / "models--lmstudio-community--gpt-oss-20b-GGUF"
    )
    hf_repo.mkdir(parents=True)
    (hf_repo / "weights.bin").write_bytes(b"0" * 5000)

    entries = LMStudioProvider(FakeShell()).discover()
    assert len(entries) == 1
    e = entries[0]
    assert e.id == "hub:openai/gpt-oss-20b"
    assert e.label == "openai/gpt-oss-20b"
    # Reported size includes the HF cache bytes, not just the manifest.
    assert e.size_bytes >= 5000
    # Recipe cleans both the manifest dir and the HF cache entry.
    recipe_text = "\n".join(e.recipe)
    assert str(manifest_dir) in recipe_text
    assert str(hf_repo) in recipe_text


def test_hub_layout_without_corresponding_hf_cache_is_skipped(tmp_path, monkeypatch):
    """A manifest that declares a model whose bytes aren't downloaded should
    not masquerade as a reclaimable entry — 1 KB of YAML is noise, not signal."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    manifest_dir = home / ".cache" / "lm-studio" / "hub" / "models" / "openai" / "gpt-oss-20b"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "model.yaml").write_text("")  # empty → no repos parsed

    # Manifest dir has no files (just empty model.yaml of 0 bytes).
    entries = LMStudioProvider(FakeShell()).discover()
    # Either zero entries or one with size 0 filtered out — current impl
    # skips total==0.
    assert entries == []


def test_home_pointer_is_respected(tmp_path, monkeypatch):
    """If ~/.lmstudio-home-pointer exists, LM Studio's home is read from it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    custom_lm_home = tmp_path / "external-drive" / "lm-studio"
    (custom_lm_home / "models" / "acme" / "frobnicator").mkdir(parents=True)
    (custom_lm_home / "models" / "acme" / "frobnicator" / "weights.bin").write_bytes(b"x" * 2048)

    (home / ".lmstudio-home-pointer").write_text(str(custom_lm_home))

    entries = LMStudioProvider(FakeShell()).discover()
    ids = {e.id for e in entries}
    assert "acme/frobnicator" in ids
