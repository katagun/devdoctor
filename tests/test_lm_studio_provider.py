from pathlib import Path

from diskdoctor.providers.lm_studio import LMStudioProvider
from diskdoctor.types import Risk
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
