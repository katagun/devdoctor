import json
import sys
from pathlib import Path

from click.testing import CliRunner

from devdoctor.cli import build_cli
from devdoctor.storage import build_storage
from devdoctor.types import ShellResult
from tests.conftest import FakeShell


def test_scan_exits_zero_and_prints_table(tmp_path, monkeypatch):
    # Isolate from real machine: empty YAML override.
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))

    # No external binaries → class providers report unavailable.
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["scan"])
    assert result.exit_code == 0, result.output
    assert "Footprint" in result.output
    assert "estimated reclaimable" in result.output


def test_scan_json_emits_valid_json(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
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
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    # Unknown risk name → user error
    result = runner.invoke(build_cli(shell), ["scan", "--risk", "maybe"])
    assert result.exit_code != 0


def test_recipe_script_is_commented(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["recipe"])
    assert result.exit_code == 0
    assert result.output.startswith("#!/usr/bin/env bash")


def test_clean_preview_does_not_prompt(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["clean"])
    assert result.exit_code == 0
    assert "Preview only" in result.output


def test_snapshot_writes_file(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["snapshot", "--note", "test"])
    assert result.exit_code == 0
    written_dir = tmp_path / "xdg" / "devdoctor" / "snapshots"
    assert written_dir.exists()
    files = list(written_dir.glob("*.json"))
    assert len(files) == 1


def test_diff_errors_when_no_snapshots(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["diff"])
    assert result.exit_code != 0
    assert "snapshot" in result.output.lower()


def test_providers_lists_registered_providers(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["providers"])
    assert result.exit_code == 0
    assert "ollama" in result.output
    assert "docker" in result.output


def _fixture(tmp_path: Path, monkeypatch) -> Path:
    """A YAML provider with one safe cache; returns the cache path."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "blob.bin").write_bytes(b"x" * 4096)
    yaml = tmp_path / "p.yaml"
    yaml.write_text(
        f"""- name: sample-cache
  description: sample
  risk: safe
  platforms: [darwin, linux]
  paths: ["{cache}"]
  recipe: "rm -rf {{path}}"
"""
    )
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    return cache


def test_clean_execute_prints_plan_progress_failure_and_records_the_run(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    shell = FakeShell(
        which_table={"ollama": None, "docker": None},
        responses={("rm", "-rf", "--", str(cache)): ShellResult(1, "", "rm: cannot remove: boom")},
    )
    result = CliRunner().invoke(
        build_cli(shell),
        ["clean", "--execute", "--yes-safe", "--yes", "--provider", "sample-cache"],
    )

    assert result.exit_code == 2, result.output
    assert "Cleanup plan — 1 entries" in result.output
    assert "sample-cache" in result.output and "rm -rf --" in result.output
    assert "[1/1] ✗ sample-cache" in result.output
    assert "failed: rm: cannot remove: boom" in result.output
    assert "Done: 0 ok · 1 failed · 0 skipped" in result.output
    assert "bytes" not in result.output.split("Done:")[1]

    (event,) = build_storage().read_audit_events(limit=1)
    assert event["source"] == "cli" and event["outcome"] == "ok"
    assert event["results"][0]["status"] == "error"
    assert event["results"][0]["message"] == "rm: cannot remove: boom"
    assert event["plan"][0]["provider"] == "sample-cache"
    assert isinstance(event["free_before_bytes"], int)


def test_clean_execute_without_a_tty_and_without_yes_aborts_before_running(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    result = CliRunner().invoke(build_cli(shell), ["clean", "--execute", "--yes-safe"])

    assert result.exit_code != 0
    assert "no terminal to confirm on; pass --yes to run unattended" in result.output
    assert shell.calls == []
    assert cache.exists()


def test_clean_risk_filter_scopes_the_run(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    result = CliRunner().invoke(
        build_cli(shell), ["clean", "--execute", "--yes-safe", "--yes", "--risk", "dangerous"]
    )
    assert result.exit_code == 0, result.output
    assert "Cleanup plan" not in result.output
    assert shell.calls == []
    assert cache.exists()


def test_history_lists_runs_and_shows_one(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    shell = FakeShell(
        which_table={"ollama": None, "docker": None},
        responses={("rm", "-rf", "--", str(cache)): ShellResult(0, "", "")},
    )
    runner = CliRunner()
    assert (
        runner.invoke(build_cli(shell), ["clean", "--execute", "--yes-safe", "--yes"]).exit_code
        == 0
    )

    listing = runner.invoke(build_cli(shell), ["history"])
    assert listing.exit_code == 0, listing.output
    assert "cli" in listing.output and "1 ok" in listing.output and "~4.0K" in listing.output

    detail = runner.invoke(build_cli(shell), ["history", "1"])
    assert detail.exit_code == 0, detail.output
    assert "sample-cache" in detail.output and "ok" in detail.output
    assert "rm -rf --" in detail.output

    as_json = runner.invoke(build_cli(shell), ["history", "--json"])
    assert as_json.exit_code == 0
    assert json.loads(as_json.output)[0]["source"] == "cli"


def test_history_with_no_runs_says_so(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    result = CliRunner().invoke(build_cli(FakeShell()), ["history"])
    assert result.exit_code == 0
    assert "no cleanup runs recorded" in result.output


def test_clean_help_describes_every_option(tmp_path, monkeypatch):
    result = CliRunner().invoke(build_cli(FakeShell()), ["clean", "--help"])
    assert result.exit_code == 0
    for flag in ("--provider", "--risk", "--execute", "--yes-safe", "--yes", "--allow-dangerous"):
        assert flag in result.output
    assert "plan still prints" in result.output
