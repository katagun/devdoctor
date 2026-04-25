from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from diskdoctor.providers.base import PathProvider
from diskdoctor.providers.ollama import OllamaProvider
from diskdoctor.types import Risk
from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Server with a curated provider list: one YAML, one class (ollama)."""
    target = tmp_path / "cache"
    target.mkdir()
    shell = FakeShell(which_table={"ollama": "/fake/bin/ollama"})

    yaml_provider = PathProvider(
        shell=shell,
        name="my-yaml",
        description="a yaml-driven provider",
        platforms=("darwin", "linux"),
        risk=Risk.SAFE,
        raw_paths=(str(target), str(tmp_path / "missing")),
        recipe_template=["rm -rf {path}"],
    )
    class_provider = OllamaProvider(shell)

    from diskdoctor import registry

    monkeypatch.setattr(
        registry,
        "load_providers",
        lambda _shell: [yaml_provider, class_provider],
    )

    yaml_file = tmp_path / "paths.yaml"
    yaml_file.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")

    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)


def _get_providers(client: TestClient) -> list[dict]:
    r = client.get("/api/providers", headers={"Host": "testserver"})
    assert r.status_code == 200
    return r.json()


def test_yaml_provider_returns_paths_and_recipe(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rows = _get_providers(client)
    yaml_row = next(r for r in rows if r["name"] == "my-yaml")

    assert isinstance(yaml_row["raw_paths"], list)
    assert len(yaml_row["raw_paths"]) == 2
    assert yaml_row["recipe_template"] == ["rm -rf {path}"]
    assert yaml_row["details"] is None


def test_class_provider_returns_details_not_paths(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rows = _get_providers(client)
    class_row = next(r for r in rows if r["name"] == "ollama")

    assert isinstance(class_row["details"], str) and class_row["details"]
    assert class_row["raw_paths"] is None
    assert class_row["resolved_paths"] is None
    assert class_row["recipe_template"] is None


def test_resolved_paths_only_includes_existing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rows = _get_providers(client)
    yaml_row = next(r for r in rows if r["name"] == "my-yaml")

    assert len(yaml_row["resolved_paths"]) == 1
    assert yaml_row["resolved_paths"][0].endswith("cache")
