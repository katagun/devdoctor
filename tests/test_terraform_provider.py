"""Terraform workspaces: .terraform is re-creatable, and duplicate plugins are measured (#82)."""

from __future__ import annotations

from pathlib import Path

from devdoctor.providers.project_artifacts import ProjectArtifactIndex, TerraformProvider
from devdoctor.types import DeletePathAction, Risk
from tests.conftest import FakeShell

PLUGIN = Path("registry.terraform.io/hashicorp/aws/5.31.0/darwin_arm64")


def _plugin(dot_terraform: Path, size: int, name: Path = PLUGIN) -> None:
    binary = dot_terraform / "providers" / name / "terraform-provider-aws"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"x" * size)


def _workspace(root: Path, name: str, *, marker: str = ".terraform.lock.hcl") -> Path:
    workspace = root / name
    workspace.mkdir(parents=True)
    (workspace / marker).write_text("# lock\n")
    return workspace / ".terraform"


def test_each_workspace_is_a_reclaimable_deletion(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    dev = _workspace(root / "infra", "dev")
    prod = _workspace(root / "infra", "prod", marker="main.tf")
    _plugin(dev, 40_000)
    _plugin(prod, 40_000)
    (prod / "modules").mkdir()
    (prod / "modules" / "vpc.tf").write_bytes(b"m" * 1_000)

    provider = TerraformProvider(FakeShell(), index=ProjectArtifactIndex())
    entries = sorted(provider.discover(), key=lambda e: str(e.path))

    assert [e.path for e in entries] == [dev, prod]
    for entry in entries:
        assert entry.risk is Risk.RECLAIMABLE
    assert entries[0].actions == (DeletePathAction(dev / "providers"),)
    assert entries[1].actions == (
        DeletePathAction(prod / "providers"),
        DeletePathAction(prod / "modules"),
    )
    assert entries[1].label == "prod/.terraform"


def test_duplicate_plugin_copies_are_measured_and_the_cache_is_advised(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    # Three workspaces hold the same aws plugin; one also holds a random plugin
    # nobody else has. Only the second and third aws copies are duplicate space.
    for name in ("a", "b", "c"):
        _plugin(_workspace(root, name), 100_000)
    _plugin(
        root / "c" / ".terraform",
        30_000,
        Path("registry.terraform.io/hashicorp/random/3.6.0/darwin_arm64"),
    )

    provider = TerraformProvider(FakeShell(), index=ProjectArtifactIndex())
    provider.discover()

    (note,) = provider.diagnostics
    assert note.startswith("terraform-workspaces: ")
    assert "across 3 workspaces" in note
    assert "TF_PLUGIN_CACHE_DIR" in note
    total, duplicate = _figures(note)
    # Human units round, and allocation may round up to the block: a few percent.
    assert 320_000 <= total <= 345_000
    assert 190_000 <= duplicate <= 215_000


def test_a_single_workspace_gets_no_cache_advice(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    _plugin(_workspace(root, "only"), 50_000)

    provider = TerraformProvider(FakeShell(), index=ProjectArtifactIndex())
    entries = provider.discover()

    assert len(entries) == 1
    assert provider.diagnostics == []


def test_a_selection_measures_its_workspace_and_skips_the_plugin_note(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    dev = _workspace(root / "infra", "dev")
    prod = _workspace(root / "infra", "prod")
    _plugin(dev, 40_000)
    _plugin(prod, 40_000)

    full = TerraformProvider(FakeShell(), index=ProjectArtifactIndex())
    everything = full.discover()
    assert any("duplicate copies" in note for note in full.diagnostics)

    selective = TerraformProvider(FakeShell(), index=ProjectArtifactIndex())
    assert selective.discover_selected(frozenset({str(dev)})) == [
        e for e in everything if e.id == str(dev)
    ]
    # The note measures every workspace's plugins; a cleanup's re-check never shows it.
    assert selective.diagnostics == []


def _figures(note: str) -> tuple[int, int]:
    """The two byte figures in the note, parsed back from human units."""
    import re

    units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3}
    found = re.findall(r"(\d+(?:\.\d+)?)([BKMG])", note)
    assert len(found) >= 2, note
    (t_num, t_unit), (d_num, d_unit) = found[0], found[1]
    return int(float(t_num) * units[t_unit]), int(float(d_num) * units[d_unit])


def test_cleanup_keeps_the_selected_workspace_and_backend_config(
    tmp_path: Path, monkeypatch
) -> None:
    """`.terraform` also holds `environment` (the selected workspace) and the backend
    config `init` was given; deleting the directory made the next apply target
    `default`. Only the re-downloadable parts are removed, and only they are counted."""
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    dot = _workspace(root / "infra", "prod")
    _plugin(dot, 40_000)
    (dot / "environment").write_text("production")
    (dot / "terraform.tfstate").write_bytes(b"s" * 20_000)

    (entry,) = TerraformProvider(FakeShell(), index=ProjectArtifactIndex()).discover()

    assert entry.path == dot
    assert entry.actions == (DeletePathAction(dot / "providers"),)
    assert entry.reclaimable_bytes is not None
    assert entry.reclaimable_bytes < entry.footprint_bytes


def test_a_workspace_with_nothing_re_downloadable_is_not_offered(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    dot = _workspace(root / "infra", "prod")
    dot.mkdir()
    (dot / "environment").write_text("production")

    assert TerraformProvider(FakeShell(), index=ProjectArtifactIndex()).discover() == []
