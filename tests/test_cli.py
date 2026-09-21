import json
import sys
from pathlib import Path

import click.testing
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


def _reclaimable_fixture(tmp_path: Path, monkeypatch) -> Path:
    """A YAML provider with one reclaimable (not safe) cache; returns the cache path."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "blob.bin").write_bytes(b"x" * 4096)
    yaml = tmp_path / "p.yaml"
    yaml.write_text(
        f"""- name: sample-cache
  description: sample
  risk: reclaimable
  platforms: [darwin, linux]
  paths: ["{cache}"]
  recipe: "rm -rf {{path}}"
"""
    )
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    return cache


class InterruptingShell(FakeShell):
    """A FakeShell whose run() raises KeyboardInterrupt, as Ctrl-C mid-command would."""

    def run(self, argv, *, check=False, timeout=None, env=None):
        raise KeyboardInterrupt


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
    assert "Cleanup plan — 1 entry" in result.output
    assert "sample-cache" in result.output and "rm -rf --" in result.output
    assert "[1/1] ✗ sample-cache" in result.output
    # CliRunner's console is 80 columns and tmp_path is long, so the on-screen line
    # truncates the failure text (F3); the full message still lands in the audit
    # event below, which is the authoritative record spec §4.3 calls for.
    assert "failed:" in result.output
    assert "…" in result.output
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


def test_clean_declined_at_confirm_records_an_aborted_outcome(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    # CliRunner swaps in its own stdin object once invoke() starts, so the isatty
    # patch on today's sys.stdin (in _fixture) never reaches it; patch the class
    # CliRunner actually uses instead so the confirm-on-a-terminal gate lets us in.
    monkeypatch.setattr(click.testing._NamedTextIOWrapper, "isatty", lambda self: True)
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    # --yes-safe auto-approves the safe entry, but not the final confirm — "n"
    # declines it there.
    result = CliRunner().invoke(
        build_cli(shell),
        ["clean", "--execute", "--yes-safe", "--provider", "sample-cache"],
        input="n\n",
    )

    assert result.exit_code == 0, result.output
    assert shell.calls == []
    (event,) = build_storage().read_audit_events(limit=1)
    assert event["outcome"] == "aborted"
    assert event["results"][0]["message"] == "aborted at confirm"


def test_clean_yes_without_a_tty_or_yes_safe_quits_at_the_per_entry_prompt(tmp_path, monkeypatch):
    cache = _reclaimable_fixture(tmp_path, monkeypatch)
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    # --yes only skips the final confirm; a reclaimable (not safe) entry still needs
    # a per-entry prompt, and CliRunner's stdin is never a tty to answer it on.
    result = CliRunner().invoke(
        build_cli(shell), ["clean", "--execute", "--yes", "--provider", "sample-cache"]
    )

    assert result.exit_code == 0, result.output
    assert "quitting" in result.output
    assert shell.calls == []
    assert cache.exists()
    (event,) = build_storage().read_audit_events(limit=1)
    assert event["outcome"] == "aborted"


def test_clean_ctrl_c_mid_run_records_interrupted_and_exits_130(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    shell = InterruptingShell(which_table={"ollama": None, "docker": None})
    result = CliRunner().invoke(
        build_cli(shell),
        ["clean", "--execute", "--yes-safe", "--yes", "--provider", "sample-cache"],
    )

    assert result.exit_code == 130, result.output
    assert "Done:" in result.output
    assert cache.exists()
    (event,) = build_storage().read_audit_events(limit=1)
    assert event["outcome"] == "interrupted"


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


def _empty_catalogue(tmp_path, monkeypatch) -> FakeShell:
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    return FakeShell(which_table={"ollama": None, "docker": None})


def test_an_unknown_provider_name_is_a_usage_error(tmp_path, monkeypatch):
    """The filter now decides what runs, so a typo would scan nothing and say nothing."""
    shell = _empty_catalogue(tmp_path, monkeypatch)
    for command in (["scan"], ["clean"], ["recipe"]):
        result = CliRunner().invoke(build_cli(shell), [*command, "--provider", "dcoker"])
        assert result.exit_code == 2, (command, result.output)
        assert "unknown provider: dcoker" in result.output
        assert "devdoctor providers" in result.output


def test_provider_names_may_be_comma_separated(tmp_path, monkeypatch):
    shell = _empty_catalogue(tmp_path, monkeypatch)
    result = CliRunner().invoke(build_cli(shell), ["scan", "--json", "--provider", "docker,ollama"])
    assert result.exit_code == 0, result.output


def _two_caches(tmp_path, monkeypatch) -> FakeShell:
    """An old small cache and a fresh large one, behind one YAML provider."""
    import os
    import time

    old, fresh = tmp_path / "old-cache", tmp_path / "fresh-cache"
    for directory, payload in ((old, b"x" * 10), (fresh, b"x" * 5000)):
        directory.mkdir()
        (directory / "f").write_bytes(payload)
    a_year_ago = time.time() - 400 * 86400
    os.utime(old, (a_year_ago, a_year_ago))
    yaml = tmp_path / "p.yaml"
    yaml.write_text(
        "- name: caches\n"
        "  description: t\n"
        "  risk: safe\n"
        "  platforms: [darwin, linux]\n"
        f"  paths: [{old}, {fresh}]\n"
        "  recipe: 'rm -rf {path}'\n"
    )
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    return FakeShell(which_table={"ollama": None, "docker": None})


def _labels(result) -> list[str]:
    return [Path(e["path"]).name for e in json.loads(result.output)["entries"]]


def test_scan_older_than_keeps_only_entries_untouched_for_that_long(tmp_path, monkeypatch):
    shell = _two_caches(tmp_path, monkeypatch)
    everything = CliRunner().invoke(build_cli(shell), ["scan", "--json", "--provider", "caches"])
    assert _labels(everything) == ["fresh-cache", "old-cache"]  # by size

    result = CliRunner().invoke(
        build_cli(shell), ["scan", "--json", "--provider", "caches", "--older-than", "6mo"]
    )
    assert result.exit_code == 0, result.output
    assert _labels(result) == ["old-cache"]


def test_scan_sort_age_lists_the_longest_untouched_first(tmp_path, monkeypatch):
    shell = _two_caches(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        build_cli(shell), ["scan", "--json", "--provider", "caches", "--sort", "age"]
    )
    assert result.exit_code == 0, result.output
    assert _labels(result) == ["old-cache", "fresh-cache"]


def test_an_unreadable_duration_is_a_usage_error(tmp_path, monkeypatch):
    shell = _two_caches(tmp_path, monkeypatch)
    for command in (["scan"], ["clean"]):
        result = CliRunner().invoke(build_cli(shell), [*command, "--older-than", "3m"])
        assert result.exit_code == 2, (command, result.output)
        assert "use e.g. 12h, 90d, 2w, 6mo, 1y" in result.output


def test_clean_older_than_never_touches_a_fresh_entry(tmp_path, monkeypatch):
    shell = _two_caches(tmp_path, monkeypatch)
    remove_old = ("rm", "-rf", "--", str((tmp_path / "old-cache").resolve()))
    shell.responses[remove_old] = ShellResult(0, "", "")
    result = CliRunner().invoke(
        build_cli(shell),
        [
            "clean",
            "--execute",
            "--yes-safe",
            "--yes",
            "--provider",
            "caches",
            "--older-than",
            "90d",
        ],
    )
    assert result.exit_code == 0, result.output
    # FakeShell raises on any unconfigured command, so the fresh cache was never offered.
    assert [call for call in shell.calls if call[0] == "rm"] == [remove_old]


def test_scan_coverage_lists_what_no_provider_accounts_for(tmp_path, monkeypatch):
    shell = _two_caches(tmp_path, monkeypatch)
    home = tmp_path / "home"
    (home / "Movies" / "raw").mkdir(parents=True)
    (home / "Movies" / "raw" / "clip.mov").write_bytes(b"x" * 4000)
    monkeypatch.setenv("HOME", str(home))

    result = CliRunner().invoke(build_cli(shell), ["scan", "--json", "--coverage"])
    assert result.exit_code == 0, result.output
    coverage = json.loads(result.output)["coverage"]
    assert coverage["unclassified"][0] == {
        "path": str((home / "Movies" / "raw").resolve()),
        "bytes": 4000,
        "files_only": False,
    }


def test_coverage_refuses_a_filtered_scan(tmp_path, monkeypatch):
    shell = _two_caches(tmp_path, monkeypatch)
    result = CliRunner().invoke(build_cli(shell), ["scan", "--coverage", "--provider", "caches"])
    assert result.exit_code == 2
    assert "--coverage describes the whole scan" in result.output
