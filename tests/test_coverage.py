import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from devdoctor import coverage
from devdoctor.coverage import Coverage, Unclassified, summarise, unclassified_directories
from devdoctor.types import DiskUsage, Entry, Report, Risk


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _entry(path: Path | None, footprint: int | None) -> Entry:
    return Entry(
        provider="p",
        id=str(path),
        path=path,
        label=str(path),
        size_bytes=footprint or 0,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
        usage=DiskUsage(footprint, footprint),
    )


def test_summarise_compares_what_is_classified_with_what_the_volume_uses(tmp_path):
    entries = [_entry(tmp_path / "a", 300), _entry(None, None), _entry(tmp_path / "b", 100)]
    result = summarise(entries, tmp_path, disk_usage=lambda _path: (10_000, 2_000, 8_000))
    assert result == Coverage(used_bytes=2_000, classified_bytes=400)
    assert result.ratio == pytest.approx(0.2)


def test_summarise_survives_a_home_that_does_not_exist(tmp_path):
    seen: list[Path] = []

    def usage(path):
        seen.append(Path(path))
        return (10, 5, 5)

    summarise([], tmp_path / "no" / "such" / "home", disk_usage=usage)
    assert seen == [tmp_path]  # the nearest ancestor that exists


def test_summarise_gives_up_quietly_when_the_volume_cannot_be_read(tmp_path):
    def usage(_path):
        raise OSError("no such volume")

    assert summarise([], tmp_path, disk_usage=usage) is None


def test_a_volume_reporting_nothing_used_has_no_ratio():
    assert Coverage(used_bytes=0, classified_bytes=0).ratio is None


def test_unclassified_directories_are_sized_at_depth_and_skip_what_is_classified(tmp_path):
    home = tmp_path / "home"
    _write(home / "Library" / "App" / "Foo" / "deep" / "blob", 5_000)  # depth 3 leaf: Foo
    _write(home / "Library" / "App" / "Bar" / "blob", 900)
    _write(home / "Library" / "App" / "loose.bin", 70)  # files directly in a walked dir
    _write(home / "Downloads" / "movie.mkv", 3_000)  # a shallow dir with no subdirs
    _write(home / ".cache" / "uv" / "wheel", 9_999)  # classified directory
    _write(home / "projects" / "app" / "node_modules" / "m.js", 8_888)  # classified, nested
    _write(home / "projects" / "app" / "src" / "main.py", 40)
    _write(home / "big.iso", 7_000)  # classified file
    _write(home / "notes.txt", 11)

    found = unclassified_directories(
        home,
        [home / ".cache" / "uv", home / "projects" / "app" / "node_modules", home / "big.iso"],
        depth=3,
        limit=10,
    )
    assert [(str(u.path.relative_to(home)), u.bytes, u.files_only) for u in found.directories] == [
        ("Library/App/Foo", 5_000, False),
        ("Downloads", 3_000, False),
        ("Library/App/Bar", 900, False),
        ("Library/App", 70, True),
        ("projects/app/src", 40, False),
        (".", 11, True),
    ]
    assert found.skipped == 0


def test_unclassified_directories_keeps_only_the_largest(tmp_path):
    home = tmp_path / "home"
    for index in range(5):
        _write(home / f"d{index}" / "f", (index + 1) * 100)
    found = unclassified_directories(home, [], depth=3, limit=2)
    assert [u.path.name for u in found.directories] == ["d4", "d3"]


def test_unclassified_directories_never_follows_a_symlink_out_of_home(tmp_path):
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    _write(outside / "huge", 50_000)
    _write(home / "real" / "f", 10)
    (home / "link").symlink_to(outside, target_is_directory=True)
    found = unclassified_directories(home, [], depth=3, limit=10)
    # The link itself occupies a few bytes in home; its 50 kB target is never entered.
    assert sum(u.bytes for u in found.directories) < 1_000
    assert "real" in [u.path.name for u in found.directories]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
def test_unreadable_directories_are_counted_not_fatal(tmp_path):
    home = tmp_path / "home"
    _write(home / "open" / "f", 10)
    locked = home / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        found = unclassified_directories(home, [], depth=3, limit=10)
    finally:
        locked.chmod(0o755)
    assert [u.path.name for u in found.directories] == ["open"]
    assert found.skipped == 1


def test_coverage_survives_the_json_round_trip(tmp_path):
    detail = Coverage(
        used_bytes=2_000,
        classified_bytes=400,
        unclassified=(Unclassified(tmp_path / "Library", 900, False),),
        skipped=2,
    )
    report = Report(
        entries=[],
        scanned_at=datetime.now(UTC),
        hostname="h",
        platform="darwin",
        coverage=detail,
    )
    payload = json.loads(report.to_json())["coverage"]
    assert payload == {
        "used_bytes": 2_000,
        "classified_bytes": 400,
        "ratio": 0.2,
        "unclassified": [{"path": str(tmp_path / "Library"), "bytes": 900, "files_only": False}],
        "skipped": 2,
    }
    assert Report.from_json(report.to_json()).coverage == detail


def test_a_report_without_coverage_round_trips_as_none():
    report = Report(entries=[], scanned_at=datetime.now(UTC), hostname="h", platform="darwin")
    assert json.loads(report.to_json())["coverage"] is None
    payload = json.loads(report.to_json())
    del payload["coverage"]  # a snapshot written before coverage existed
    assert Report.from_json(json.dumps(payload)).coverage is None


def test_a_filtered_view_drops_coverage():
    report = Report(
        entries=[],
        scanned_at=datetime.now(UTC),
        hostname="h",
        platform="darwin",
        coverage=Coverage(10, 5),
    )
    assert report.filter(min_size=1).coverage is None


def test_the_module_reads_the_real_volume_by_default(tmp_path):
    result = coverage.summarise([], tmp_path)
    assert result is not None and result.used_bytes > 0


_DF = """Filesystem   1024-blocks      Used Available Capacity  Mounted on
/dev/disk3s5   482797652 416043196  16366832    97%    /System/Volumes/Data
"""


def test_used_space_is_the_volumes_own_not_the_containers():
    """On APFS, total minus free also counts the system, swap and preboot volumes."""
    assert coverage._parse_df(_DF) == (482797652 * 1024, 416043196 * 1024, 16366832 * 1024)


@pytest.mark.parametrize("output", ["", "Filesystem 1024-blocks Used\n", "a b c\nx y z w v u\n"])
def test_unreadable_df_output_is_not_trusted(output):
    assert coverage._parse_df(output) is None


def test_volume_usage_falls_back_when_df_is_missing(tmp_path, monkeypatch):
    def no_df(*_args, **_kwargs):
        raise FileNotFoundError("df")

    monkeypatch.setattr(coverage.subprocess, "run", no_df)
    total, used, free = coverage.volume_usage(tmp_path)
    assert total > 0 and used > 0 and free >= 0


def test_df_lines_with_spaces_in_the_device_and_mount_point_still_parse():
    output = "Filesystem 1024-blocks Used Available Capacity Mounted on\nmap auto home 100 40 60 40% /Volumes/My Disk\n"
    assert coverage._parse_df(output) == (100 * 1024, 40 * 1024, 60 * 1024)


def test_a_classified_path_spelled_in_another_case_is_still_excluded(tmp_path):
    """APFS is case-insensitive: a provider may spell a path differently from the disk."""
    home = tmp_path / "home"
    _write(home / "Library" / "Caches" / "blob", 9_000)
    _write(home / "Library" / "Other" / "blob", 50)
    misspelled = home / "library" / "caches"
    if not misspelled.exists():
        pytest.skip("case-sensitive filesystem")

    found = unclassified_directories(home, [misspelled], depth=3, limit=10)
    assert [(u.path.name, u.bytes) for u in found.directories] == [("Other", 50)]


def test_a_classified_file_with_a_second_name_is_excluded_under_both(tmp_path):
    home = tmp_path / "home"
    _write(home / "models" / "a.gguf", 4_000)
    (home / "elsewhere").mkdir()
    os.link(home / "models" / "a.gguf", home / "elsewhere" / "same.gguf")
    _write(home / "elsewhere" / "other", 7)

    found = unclassified_directories(home, [home / "models" / "a.gguf"], depth=3, limit=10)
    assert [(u.path.name, u.bytes) for u in found.directories] == [("elsewhere", 7)]
