import contextlib
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.history import diff, load_snapshot, write_snapshot
from diskdoctor.types import Entry, Report, Risk


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
    monkeypatch.setattr("diskdoctor.types.Report.to_json", boom)
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
