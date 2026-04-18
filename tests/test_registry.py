from pathlib import Path

import pytest

from diskdoctor.registry import load_providers, DuplicateProviderError
from tests.conftest import FakeShell


def test_load_providers_returns_sorted_by_name():
    providers = load_providers(FakeShell())
    names = [p.name for p in providers]
    assert names == sorted(names)


def test_load_providers_includes_yaml_entries():
    providers = load_providers(FakeShell())
    names = {p.name for p in providers}
    assert "uv-cache" in names
    assert "pip-cache" in names


def test_duplicate_yaml_names_raises(tmp_path: Path, monkeypatch):
    yaml_text = """
- name: same
  description: a
  risk: safe
  platforms: [darwin]
  paths: [~/x]
  recipe: "rm -rf {path}"
- name: same
  description: b
  risk: safe
  platforms: [darwin]
  paths: [~/y]
  recipe: "rm -rf {path}"
"""
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text(yaml_text)
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    with pytest.raises(DuplicateProviderError, match="same"):
        load_providers(FakeShell())


def test_env_override_replaces_default_yaml(tmp_path: Path, monkeypatch):
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text(
        "- name: custom\n  description: x\n  risk: safe\n  platforms: [darwin, linux]\n"
        "  paths: [~/x]\n  recipe: 'rm -rf {path}'\n"
    )
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    providers = load_providers(FakeShell())
    names = {p.name for p in providers}
    assert "custom" in names
    assert "uv-cache" not in names  # env override replaced the default


def test_malformed_yaml_raises_with_clear_message(tmp_path: Path, monkeypatch):
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text("- name: bad\n  risk: maybe\n  platforms: [darwin]\n  paths: [~/x]\n  recipe: 'x'\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    with pytest.raises(ValueError, match="risk"):
        load_providers(FakeShell())
