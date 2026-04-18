import json

from click.testing import CliRunner

from diskdoctor.cli import build_cli
from diskdoctor.types import ShellResult
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
