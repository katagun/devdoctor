from __future__ import annotations

from pathlib import Path

from devdoctor.providers.project_artifacts import (
    AndroidBuildProvider,
    CargoTargetsProvider,
    NodeModulesProvider,
    ProjectArtifactIndex,
    ToxNoxProvider,
)
from devdoctor.types import AdviceAction, DeletePathAction, Risk
from tests.conftest import FakeShell


def _payload(path: Path, size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_project_index_feeds_all_artifact_providers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))

    node = root / "node"
    _payload(node / "package.json")
    _payload(node / "pnpm-lock.yaml")
    _payload(node / "node_modules" / "pkg" / "index.js")

    cargo = root / "cargo"
    _payload(cargo / "Cargo.toml")
    _payload(cargo / "target" / "debug" / "app")

    android = root / "android"
    _payload(android / "build.gradle.kts")
    _payload(android / "build" / "outputs" / "app.apk")

    python = root / "python"
    _payload(python / "tox.ini")
    _payload(python / ".tox" / "py312" / "marker")
    _payload(python / ".nox" / "lint" / "marker")

    index = ProjectArtifactIndex()
    shell = FakeShell()
    providers = (
        NodeModulesProvider(shell, index=index),
        CargoTargetsProvider(shell, index=index),
        AndroidBuildProvider(shell, index=index),
        ToxNoxProvider(shell, index=index),
    )

    entries = {provider.name: provider.discover() for provider in providers}

    assert [entry.path for entry in entries["node-project-dependencies"]] == [node / "node_modules"]
    assert [entry.path for entry in entries["cargo-targets"]] == [cargo / "target"]
    assert [entry.path for entry in entries["android-project-builds"]] == [android / "build"]
    assert {entry.path for entry in entries["tox-nox-environments"]} == {
        python / ".tox",
        python / ".nox",
    }
    assert all(
        isinstance(entry.actions[0], DeletePathAction)
        for rows in entries.values()
        for entry in rows
    )


def test_node_modules_without_lockfile_is_dangerous_advice(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    project = root / "unlocked"
    _payload(project / "package.json")
    _payload(project / "node_modules" / "pkg" / "index.js")

    [entry] = NodeModulesProvider(FakeShell()).discover()

    assert entry.risk == Risk.DANGEROUS
    assert entry.reclaimable_bytes is None
    assert isinstance(entry.actions[0], AdviceAction)


def test_project_index_does_not_follow_symlinked_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    project = root / "linked"
    external = tmp_path / "external"
    _payload(project / "package.json")
    _payload(project / "package-lock.json")
    _payload(external / "pkg" / "index.js")
    (project / "node_modules").symlink_to(external, target_is_directory=True)

    assert NodeModulesProvider(FakeShell()).discover() == []
