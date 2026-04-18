from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.history import load_snapshot, write_snapshot
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
