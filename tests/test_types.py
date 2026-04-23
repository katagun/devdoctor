import json
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.types import (
    CleanResult,
    CleanupOpts,
    DiffReport,
    DiffRow,
    Entry,
    Report,
    Risk,
    ScanFilters,
    ShellResult,
)


def test_risk_is_string_enum_with_three_levels():
    assert Risk.SAFE.value == "safe"
    assert Risk.RECLAIMABLE.value == "reclaimable"
    assert Risk.DANGEROUS.value == "dangerous"
    assert set(Risk) == {Risk.SAFE, Risk.RECLAIMABLE, Risk.DANGEROUS}


def test_entry_is_frozen():
    e = Entry(
        provider="ollama",
        id="llama3:8b",
        path=None,
        label="llama3:8b",
        size_bytes=4_700_000_000,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=["ollama rm llama3:8b"],
    )
    import pytest

    with pytest.raises(AttributeError):
        e.size_bytes = 0  # type: ignore[misc]


def test_report_helpers():
    now = datetime(2026, 4, 18, tzinfo=UTC)
    e1 = Entry("a", "1", Path("/x"), "a/1", 100, None, Risk.SAFE, ["rm -rf /x"])
    e2 = Entry("a", "2", Path("/y"), "a/2", 200, None, Risk.SAFE, ["rm -rf /y"])
    e3 = Entry("b", "1", Path("/z"), "b/1", 50, None, Risk.DANGEROUS, ["rm -rf /z"])
    r = Report(entries=[e1, e2, e3], scanned_at=now, hostname="h", platform="darwin")

    assert r.total_bytes() == 350
    assert list(r.by_provider().keys()) == ["a", "b"]
    assert len(r.by_provider()["a"]) == 2

    safe_only = r.filter(risks={Risk.SAFE})
    assert [e.id for e in safe_only.entries] == ["1", "2"]

    by_name = r.filter(providers={"b"})
    assert [e.provider for e in by_name.entries] == ["b"]

    big = r.filter(min_size=150)
    assert [e.size_bytes for e in big.entries] == [200]


def test_report_json_round_trip():
    now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
    e = Entry("a", "1", Path("/x"), "a/1", 100, 1_700_000_000.0, Risk.SAFE, ["rm -rf /x"])
    r = Report(
        entries=[e],
        scanned_at=now,
        hostname="h",
        platform="darwin",
        note="after cleanup",
        skipped_paths=["/forbidden"],
    )
    blob = r.to_json()
    r2 = Report.from_json(blob)
    assert r2.hostname == r.hostname
    assert r2.platform == r.platform
    assert r2.note == r.note
    assert r2.skipped_paths == r.skipped_paths
    assert r2.scanned_at == r.scanned_at
    assert len(r2.entries) == 1
    assert r2.entries[0] == e


def test_clean_result_status_values():
    ok = CleanResult(entry_id="x", status="ok", freed_bytes=10)
    dry = CleanResult(entry_id="x", status="dry_run", freed_bytes=10)
    err = CleanResult(entry_id="x", status="error", freed_bytes=0, message="boom")
    skipped = CleanResult(entry_id="x", status="skipped", freed_bytes=0)
    assert (ok.status, dry.status, err.status, skipped.status) == (
        "ok",
        "dry_run",
        "error",
        "skipped",
    )


def test_scan_filters_defaults_include_everything():
    f = ScanFilters()
    assert f.min_size_bytes == 0
    assert f.risks is None
    assert f.providers is None


def test_cleanup_opts_defaults_are_safe():
    o = CleanupOpts()
    assert o.execute is False
    assert o.yes_safe is False
    assert o.allow_dangerous is False
    assert o.providers is None


def test_diff_row_and_report():
    now = datetime(2026, 4, 18, tzinfo=UTC)
    row = DiffRow(provider="a", before_bytes=100, after_bytes=20, delta_bytes=-80, delta_pct=-80.0)
    d = DiffReport(before_at=now, after_at=now, rows=[row])
    assert d.rows[0].provider == "a"


def test_shell_result_is_frozen():
    import pytest

    sr = ShellResult(returncode=0, stdout="ok", stderr="")
    with pytest.raises(AttributeError):
        sr.returncode = 1  # type: ignore[misc]


def test_report_filter_combines_with_and():
    now = datetime(2026, 4, 18, tzinfo=UTC)
    entries = [
        Entry("a", "1", Path("/x"), "a/1", 100, None, Risk.SAFE, ["rm -rf /x"]),
        Entry("a", "2", Path("/y"), "a/2", 500, None, Risk.DANGEROUS, ["rm -rf /y"]),
        Entry("b", "1", Path("/z"), "b/1", 200, None, Risk.SAFE, ["rm -rf /z"]),
        Entry("b", "2", Path("/w"), "b/2", 50, None, Risk.SAFE, ["rm -rf /w"]),
    ]
    r = Report(entries=entries, scanned_at=now, hostname="h", platform="darwin")
    filtered = r.filter(risks={Risk.SAFE}, min_size=150, providers={"b"})
    # Only b/1 is SAFE AND >=150 AND provider=b
    assert [(e.provider, e.id, e.size_bytes) for e in filtered.entries] == [("b", "1", 200)]


def _make_entry(**overrides) -> Entry:
    base = {
        "provider": "test",
        "id": "e1",
        "path": Path("/tmp/foo"),
        "label": "/tmp/foo",
        "size_bytes": 100,
        "mtime": 1700000000.0,
        "risk": Risk.SAFE,
        "recipe": ["rm -rf /tmp/foo"],
    }
    base.update(overrides)
    return Entry(**base)


def test_entry_new_fields_default_to_none() -> None:
    e = _make_entry()
    assert e.uid is None
    assert e.gid is None
    assert e.mode is None
    assert e.owner is None
    assert e.group is None
    assert e.perms is None


def test_entry_new_fields_accept_values() -> None:
    e = _make_entry(uid=501, gid=20, mode=16877, owner="shamil", group="staff", perms="drwxr-xr-x")
    assert e.uid == 501
    assert e.gid == 20
    assert e.mode == 16877
    assert e.owner == "shamil"
    assert e.group == "staff"
    assert e.perms == "drwxr-xr-x"


def _make_report(entries: list[Entry]) -> Report:
    return Report(
        entries=entries,
        scanned_at=datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC),
        hostname="test-host",
        platform="darwin",
    )


def test_report_round_trip_preserves_new_fields() -> None:
    e = _make_entry(uid=501, gid=20, mode=16877, owner="shamil", group="staff", perms="drwxr-xr-x")
    raw = _make_report([e]).to_json()
    restored = Report.from_json(raw)
    assert len(restored.entries) == 1
    r = restored.entries[0]
    assert r.uid == 501
    assert r.gid == 20
    assert r.mode == 16877
    assert r.owner == "shamil"
    assert r.group == "staff"
    assert r.perms == "drwxr-xr-x"


def test_report_round_trip_entry_without_stat_fields() -> None:
    e = _make_entry(path=None)  # class-based provider entry (e.g. ollama model)
    raw = _make_report([e]).to_json()
    restored = Report.from_json(raw)
    r = restored.entries[0]
    assert r.uid is None
    assert r.owner is None
    assert r.perms is None


def test_old_snapshot_without_new_fields_deserializes_with_none() -> None:
    # Simulate a snapshot from a pre-feature version: no uid/gid/mode/owner/group/perms keys.
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "provider": "test",
                "id": "e1",
                "path": "/tmp/foo",
                "label": "/tmp/foo",
                "size_bytes": 100,
                "mtime": 1700000000.0,
                "risk": "safe",
                "recipe": ["rm -rf /tmp/foo"],
            }
        ],
        "scanned_at": "2026-04-23T12:00:00+00:00",
        "hostname": "test-host",
        "platform": "darwin",
        "note": None,
        "skipped_paths": [],
    }
    restored = Report.from_json(json.dumps(payload))
    assert len(restored.entries) == 1
    r = restored.entries[0]
    assert r.uid is None
    assert r.gid is None
    assert r.mode is None
    assert r.owner is None
    assert r.group is None
    assert r.perms is None
