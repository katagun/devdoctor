"""Tests for the Time Machine local snapshots provider."""

from devdoctor.types import CommandAction, DiskUsage, Risk, ShellResult
from tests.conftest import FakeShell

_LIST_ARGV = ("tmutil", "listlocalsnapshots", "/")

_FIXTURE_OUTPUT = """Snapshots for volume group containing disk /:
com.apple.TimeMachine.2026-09-18-100000.local
com.apple.os.update-8D1F2C3E4A5B6D.local
com.apple.TimeMachine.2026-09-19-080000.local
junk line that is not a snapshot
com.apple.TimeMachine.2026-09-19-090000.local
com.apple.os.update-FFFFFFFFFFFF.local
"""

_TS_OLD = "2026-09-18-100000"
_TS_MID = "2026-09-19-080000"
_TS_NEW = "2026-09-19-090000"


def _shell_with_output(output: str) -> FakeShell:
    return FakeShell(
        which_table={"tmutil": "/usr/bin/tmutil"},
        responses={_LIST_ARGV: ShellResult(0, output, "")},
    )


def test_discover_runs_exact_tmutil_argv(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    shell = _shell_with_output(_FIXTURE_OUTPUT)
    TimeMachineSnapshotsProvider(shell).discover()
    assert shell.calls == [_LIST_ARGV]


def test_discover_filters_os_update_snapshots(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    entries = TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    per_snapshot = [e for e in entries if e.id.startswith("snapshot-")]
    assert {e.id for e in per_snapshot} == {
        f"snapshot-{_TS_OLD}",
        f"snapshot-{_TS_MID}",
        f"snapshot-{_TS_NEW}",
    }
    assert all("os.update" not in e.id for e in entries)


def test_per_snapshot_labels_use_human_timestamp(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    by_id = {
        e.id: e
        for e in TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    }
    assert by_id[f"snapshot-{_TS_OLD}"].label == "Time Machine local snapshot 2026-09-18 10:00:00"
    assert by_id[f"snapshot-{_TS_NEW}"].label == "Time Machine local snapshot 2026-09-19 09:00:00"


def test_newest_excluded_from_bundle_actions_but_present_as_entry(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    by_id = {
        e.id: e
        for e in TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    }
    bundle = by_id["all-but-newest"]
    assert f"snapshot-{_TS_NEW}" in by_id
    bundle_argvs = [a.argv for a in bundle.actions if isinstance(a, CommandAction)]
    assert all(_TS_NEW not in argv for argv in bundle_argvs)
    assert len(bundle_argvs) == 2


def test_bundle_actions_are_newest_first(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    by_id = {
        e.id: e
        for e in TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    }
    bundle = by_id["all-but-newest"]
    assert [a.argv for a in bundle.actions if isinstance(a, CommandAction)] == [
        ("tmutil", "deletelocalsnapshots", _TS_MID),
        ("tmutil", "deletelocalsnapshots", _TS_OLD),
    ]


def test_bundle_covers_every_snapshot_id_including_newest(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    by_id = {
        e.id: e
        for e in TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    }
    assert by_id["all-but-newest"].covers == (
        f"snapshot-{_TS_OLD}",
        f"snapshot-{_TS_MID}",
        f"snapshot-{_TS_NEW}",
    )


def test_bundle_mtime_is_oldest_snapshot(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    by_id = {
        e.id: e
        for e in TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    }
    bundle = by_id["all-but-newest"]
    oldest = by_id[f"snapshot-{_TS_OLD}"]
    assert bundle.mtime == oldest.mtime
    assert bundle.mtime is not None


def test_entries_are_unmeasured_and_reclaimable(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    entries = TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    assert entries, "expected bundle plus per-snapshot entries"
    for e in entries:
        assert e.size_bytes == 0
        assert e.usage == DiskUsage(None, None)
        assert e.display_bytes == 0
        assert e.risk == Risk.RECLAIMABLE
        assert e.provider == "time-machine-local-snapshots"


def test_empty_output_yields_no_entries_plus_diagnostic(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    provider = TimeMachineSnapshotsProvider(_shell_with_output("Snapshots for disk /:\n"))
    assert provider.discover() == []
    assert provider.diagnostics, "expected a diagnostic for empty snapshot list"


def test_nonzero_exit_yields_no_entries_plus_diagnostic(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    shell = FakeShell(
        which_table={"tmutil": "/usr/bin/tmutil"},
        responses={_LIST_ARGV: ShellResult(1, "", "tmutil failed")},
    )
    provider = TimeMachineSnapshotsProvider(shell)
    assert provider.discover() == []
    assert provider.diagnostics, "expected a diagnostic for tmutil failure"


def test_unavailable_off_darwin(monkeypatch):
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    monkeypatch.setattr("sys.platform", "linux")
    shell = FakeShell(
        which_table={"tmutil": "/usr/bin/tmutil"},
        responses={},
    )
    assert TimeMachineSnapshotsProvider(shell).available() is False


def test_unavailable_when_tmutil_missing(monkeypatch):
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    monkeypatch.setattr("sys.platform", "darwin")
    assert (
        TimeMachineSnapshotsProvider(FakeShell(which_table={"tmutil": None})).available() is False
    )


def test_provider_metadata(monkeypatch):
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    monkeypatch.setattr("sys.platform", "darwin")
    assert TimeMachineSnapshotsProvider.name == "time-machine-local-snapshots"
    assert TimeMachineSnapshotsProvider.family == "system"
    assert TimeMachineSnapshotsProvider.platforms == ("darwin",)
    assert TimeMachineSnapshotsProvider.required_binary == "tmutil"
    assert TimeMachineSnapshotsProvider.risk == Risk.RECLAIMABLE
    shell = FakeShell(
        which_table={"tmutil": "/usr/bin/tmutil"},
        responses={},
    )
    assert TimeMachineSnapshotsProvider(shell).available() is True


def test_registered_in_registry():
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider
    from devdoctor.registry import _CLASS_PROVIDERS

    assert TimeMachineSnapshotsProvider in _CLASS_PROVIDERS


def test_bundle_label_counts_snapshots_it_deletes(monkeypatch):
    """The count in the bundle label is read before a destructive confirm: it
    must be the number of delete actions (2), not the total snapshots (3)."""
    monkeypatch.setattr("sys.platform", "darwin")
    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    by_id = {
        e.id: e
        for e in TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    }
    assert by_id["all-but-newest"].label == ("Time Machine local snapshots, all but the newest (2)")


def test_snapshot_mtime_uses_local_timezone(monkeypatch):
    """tmutil prints local wall-clock time; interpreting it as UTC shifts every
    mtime (and the Stale column) by the UTC offset."""
    monkeypatch.setattr("sys.platform", "darwin")
    from datetime import datetime

    from devdoctor.providers.time_machine import TimeMachineSnapshotsProvider

    by_id = {
        e.id: e
        for e in TimeMachineSnapshotsProvider(_shell_with_output(_FIXTURE_OUTPUT)).discover()
    }
    expected = datetime.strptime(_TS_OLD, "%Y-%m-%d-%H%M%S").astimezone().timestamp()
    assert by_id[f"snapshot-{_TS_OLD}"].mtime == expected
