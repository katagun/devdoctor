import json

from click.testing import CliRunner

from diskdoctor.cli import build_cli
from tests.conftest import FakeShell


def test_scan_exits_zero_and_prints_table(tmp_path, monkeypatch):
    # Isolate from real machine: empty YAML override.
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))

    # No external binaries → class providers report unavailable.
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["scan"])
    assert result.exit_code == 0, result.output
    assert "Total" in result.output


def test_scan_json_emits_valid_json(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["scan", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "entries" in data
    assert "scanned_at" in data


def test_scan_filters_by_risk(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    # Unknown risk name → user error
    result = runner.invoke(build_cli(shell), ["scan", "--risk", "maybe"])
    assert result.exit_code != 0


def test_recipe_script_is_commented(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["recipe"])
    assert result.exit_code == 0
    assert result.output.startswith("#!/usr/bin/env bash")


def test_clean_preview_does_not_prompt(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["clean"])
    assert result.exit_code == 0
    assert "Preview only" in result.output


def test_snapshot_writes_file(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["snapshot", "--note", "test"])
    assert result.exit_code == 0
    written_dir = tmp_path / "xdg" / "diskdoctor" / "snapshots"
    assert written_dir.exists()
    files = list(written_dir.glob("*.json"))
    assert len(files) == 1


def test_diff_errors_when_no_snapshots(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["diff"])
    assert result.exit_code != 0
    assert "snapshot" in result.output.lower()


def test_providers_lists_registered_providers(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["providers"])
    assert result.exit_code == 0
    assert "ollama" in result.output
    assert "docker" in result.output
