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
