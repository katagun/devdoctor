import contextlib
from datetime import UTC, datetime
from pathlib import Path

from devdoctor import history
from devdoctor.history import diff, load_snapshot, write_snapshot
from devdoctor.types import Entry, ProviderTiming, Report, Risk, SnapshotKind


def _rep(ts, entries=()) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=ts,
        hostname="h",
        platform="darwin",
    )


def test_write_snapshot_creates_file_with_iso_timestamp(tmp_path: Path):
    ts = datetime(2026, 4, 18, 12, 34, 56, tzinfo=UTC)
    r = _rep(ts)
    p = write_snapshot(r, tmp_path)
    assert p.parent == tmp_path
    assert p.suffix == ".json"
    # ISO-safe filename: no colons
    assert ":" not in p.name


def test_write_snapshot_creates_directory_if_missing(tmp_path: Path):
    target = tmp_path / "sub" / "snaps"
    ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
    p = write_snapshot(_rep(ts), target)
    assert p.parent == target


def test_write_snapshot_is_atomic_no_tmp_left_on_success(tmp_path: Path):
    ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
    p = write_snapshot(_rep(ts), tmp_path)
    # The .tmp sibling must not linger after a successful rename.
    assert p.is_file()
    assert not p.with_name(p.name + ".tmp").exists()


def test_write_snapshot_cleans_up_tmp_on_serialization_failure(tmp_path: Path, monkeypatch):
    ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)

    def boom(self):
        raise RuntimeError("boom")

    # Force to_json() to fail mid-write so the finalize step never runs.
    monkeypatch.setattr("devdoctor.types.Report.to_json", boom)
    with contextlib.suppress(RuntimeError):
        write_snapshot(_rep(ts), tmp_path)
    # Neither the real file nor the tmp should exist; the target dir is clean.
    assert list(tmp_path.glob("*.json*")) == []


def test_snapshot_includes_schema_version(tmp_path: Path):
    import json as _json

    ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
    p = write_snapshot(_rep(ts), tmp_path)
    payload = _json.loads(p.read_text())
    assert payload["schema_version"] == 2


def test_snapshot_round_trip(tmp_path: Path):
    ts = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    e = Entry(
        provider="a",
        id="1",
        path=Path("/x"),
        label="a/1",
        size_bytes=100,
        mtime=1_700_000_000.0,
        risk=Risk.SAFE,
        recipe=["rm -rf /x"],
    )
    r = _rep(ts, entries=[e])
    r.note = "post-cleanup"
    r.skipped_paths.append("/forbidden")
    p = write_snapshot(r, tmp_path)
    r2 = load_snapshot(p)
    assert r2.note == "post-cleanup"
    assert r2.skipped_paths == ["/forbidden"]
    assert r2.entries[0] == e


def _entry(provider, id_, size):
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{provider}/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=["rm -rf"],
    )


def test_diff_reports_shrinkage():
    ts_before = datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC)
    ts_after = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    before = _rep(ts_before, entries=[_entry("a", "1", 1000)])
    after = _rep(ts_after, entries=[_entry("a", "1", 200)])
    d = diff(before, after)
    assert [(r.provider, r.before_bytes, r.after_bytes, r.delta_bytes) for r in d.rows] == [
        ("a", 1000, 200, -800)
    ]
    assert d.rows[0].delta_pct == -80.0


def test_diff_handles_added_provider():
    ts_before = datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC)
    ts_after = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    before = _rep(ts_before, entries=[_entry("a", "1", 1000)])
    after = _rep(ts_after, entries=[_entry("a", "1", 1000), _entry("b", "1", 500)])
    d = diff(before, after)
    names = {r.provider for r in d.rows}
    assert names == {"a", "b"}
    b_row = next(r for r in d.rows if r.provider == "b")
    assert (b_row.before_bytes, b_row.after_bytes, b_row.delta_bytes) == (0, 500, 500)
    assert b_row.delta_pct == 0.0  # before=0 → pct defaults to 0


def test_diff_handles_removed_provider():
    ts_before = datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC)
    ts_after = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    before = _rep(ts_before, entries=[_entry("a", "1", 1000), _entry("b", "1", 500)])
    after = _rep(ts_after, entries=[_entry("a", "1", 1000)])
    d = diff(before, after)
    b_row = next(r for r in d.rows if r.provider == "b")
    assert (b_row.before_bytes, b_row.after_bytes, b_row.delta_bytes) == (500, 0, -500)
    assert b_row.delta_pct == -100.0


def _entry_stub(provider: str = "p", size: int = 100) -> Entry:
    return Entry(
        provider=provider,
        id=f"{provider}-1",
        path=Path("/tmp/x"),
        label="/tmp/x",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
    )


def _report_stub(
    kind: SnapshotKind, scanned_at: datetime, entries=None, per_provider=None
) -> Report:
    return Report(
        entries=entries or [_entry_stub()],
        scanned_at=scanned_at,
        hostname="h",
        platform="darwin",
        kind=kind,
        started_at=scanned_at,
        duration_ms=100,
        per_provider=per_provider
        or [ProviderTiming(name="p", bytes=100, entries=1, duration_ms=100)],
    )


def test_write_snapshot_uses_kind_suffix(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 24, 12, 0, 5, tzinfo=UTC)
    manual = _report_stub(SnapshotKind.MANUAL, ts)
    auto = _report_stub(SnapshotKind.AUTO, ts.replace(second=10))

    mp = history.write_snapshot(manual, tmp_path)
    ap = history.write_snapshot(auto, tmp_path)

    assert mp.name.endswith("--manual.json")
    assert ap.name.endswith("--auto.json")


def test_write_snapshot_auto_has_null_entries_on_disk(tmp_path: Path) -> None:
    import json

    ts = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    auto = _report_stub(SnapshotKind.AUTO, ts)
    path = history.write_snapshot(auto, tmp_path)
    payload = json.loads(path.read_text())
    assert payload["kind"] == "auto"
    assert payload["entries"] is None
    assert payload["per_provider"][0]["name"] == "p"
    assert payload["total_bytes"] == 100


def test_prune_auto_snapshots_keeps_newest(tmp_path: Path) -> None:
    for i in range(5):
        ts = datetime(2026, 4, 24, 12, 0, i, tzinfo=UTC)
        history.write_snapshot(_report_stub(SnapshotKind.AUTO, ts), tmp_path)
    for i in range(2):
        ts = datetime(2026, 4, 24, 13, 0, i, tzinfo=UTC)
        history.write_snapshot(_report_stub(SnapshotKind.MANUAL, ts), tmp_path)

    deleted = history.prune_auto_snapshots(tmp_path, keep=3)
    assert len(deleted) == 2

    remaining_autos = sorted(p.name for p in tmp_path.glob("*--auto.json"))
    assert len(remaining_autos) == 3

    remaining_manuals = sorted(p.name for p in tmp_path.glob("*--manual.json"))
    assert len(remaining_manuals) == 2  # untouched


def test_prune_auto_with_zero_keep_removes_all_autos(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    history.write_snapshot(_report_stub(SnapshotKind.AUTO, ts), tmp_path)
    history.write_snapshot(_report_stub(SnapshotKind.MANUAL, ts.replace(minute=1)), tmp_path)
    deleted = history.prune_auto_snapshots(tmp_path, keep=0)
    assert len(deleted) == 1
    assert list(tmp_path.glob("*--auto.json")) == []
    assert len(list(tmp_path.glob("*--manual.json"))) == 1


def test_prune_auto_on_missing_dir_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert history.prune_auto_snapshots(missing) == []


def test_diff_uses_per_provider_totals_when_available() -> None:
    ts1 = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    ts2 = datetime(2026, 4, 24, 13, 0, tzinfo=UTC)
    before = Report(
        entries=[],
        scanned_at=ts1,
        hostname="h",
        platform="darwin",
        kind=SnapshotKind.AUTO,
        started_at=ts1,
        duration_ms=10,
        per_provider=[ProviderTiming("p", 1000, 1, 10)],
    )
    after = Report(
        entries=[],
        scanned_at=ts2,
        hostname="h",
        platform="darwin",
        kind=SnapshotKind.AUTO,
        started_at=ts2,
        duration_ms=10,
        per_provider=[ProviderTiming("p", 600, 1, 10)],
    )
    report = history.diff(before, after)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.provider == "p"
    assert row.before_bytes == 1000
    assert row.after_bytes == 600
    assert row.delta_bytes == -400


def test_diff_mixed_auto_manual_symmetric() -> None:
    ts1 = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    ts2 = datetime(2026, 4, 24, 13, 0, tzinfo=UTC)
    before = Report(
        entries=[],
        scanned_at=ts1,
        hostname="h",
        platform="darwin",
        kind=SnapshotKind.AUTO,
        started_at=ts1,
        duration_ms=10,
        per_provider=[ProviderTiming("p", 1000, 1, 10)],
    )
    after = Report(
        entries=[_entry_stub(size=700)],
        scanned_at=ts2,
        hostname="h",
        platform="darwin",
        kind=SnapshotKind.MANUAL,
        started_at=ts2,
        duration_ms=10,
        per_provider=[ProviderTiming("p", 700, 1, 10)],
    )
    report = history.diff(before, after)
    assert report.rows[0].before_bytes == 1000
    assert report.rows[0].after_bytes == 700
    assert report.rows[0].delta_bytes == -300


def test_diff_v1_manual_report_falls_back_to_summing_entries() -> None:
    """Pre-feature snapshots have per_provider=[] but do have entries."""
    ts1 = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    ts2 = datetime(2026, 4, 24, 13, 0, tzinfo=UTC)
    before = Report(
        entries=[_entry_stub(size=500)],
        scanned_at=ts1,
        hostname="h",
        platform="darwin",
    )
    after = Report(
        entries=[_entry_stub(size=300)],
        scanned_at=ts2,
        hostname="h",
        platform="darwin",
    )
    report = history.diff(before, after)
    assert report.rows[0].before_bytes == 500
    assert report.rows[0].after_bytes == 300
    assert report.rows[0].delta_bytes == -200
