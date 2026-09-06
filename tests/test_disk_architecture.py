from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from devdoctor.cleanup import ConfirmRequired, iter_cleanup_events
from devdoctor.discovery import scan
from devdoctor.providers.base import Provider
from devdoctor.sizer import size_path_detailed
from devdoctor.types import (
    AdviceAction,
    CleanupOpts,
    CommandAction,
    DeletePathAction,
    DiskUsage,
    Entry,
    Report,
    Risk,
    ScanFilters,
)
from tests.conftest import FakeShell


class _EntriesProvider(Provider):
    name = "hardlinks"
    family = "test"
    description = "test"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE

    def __init__(self, entries: list[Entry]) -> None:
        super().__init__(FakeShell())
        self._entries = entries

    def discover(self) -> list[Entry]:
        return self._entries


def _path_entry(path: Path, id_: str) -> Entry:
    sizing = size_path_detailed(path)
    return Entry(
        provider="hardlinks",
        id=id_,
        path=path,
        label=id_,
        size_bytes=sizing.allocated_bytes,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
        usage=DiskUsage(sizing.allocated_bytes, sizing.allocated_bytes),
        actions=(DeletePathAction(path),),
        hardlinks=sizing.hardlinks,
    )


def _scan(entries: list[Entry]) -> Report:
    return scan(
        [_EntriesProvider(entries)],
        ScanFilters(),
        datetime(2026, 9, 5, tzinfo=UTC),
    )


def test_split_hardlinks_become_reclaimable_only_as_a_plan(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    source = left / "shared.bin"
    source.write_bytes(b"x" * 4096)
    os.link(source, right / "shared.bin")

    report = _scan([_path_entry(left, "left"), _path_entry(right, "right")])
    allocation = report.entries[0].footprint_bytes

    assert allocation is not None and allocation > 0
    assert [entry.reclaimable_bytes for entry in report.entries] == [0, 0]
    assert [entry.shared_bytes for entry in report.entries] == [allocation, allocation]
    assert report.total_footprint_bytes() == allocation
    assert report.total_reclaimable_bytes() == allocation
    assert report.total_shared_bytes() == allocation

    events = iter_cleanup_events(
        report,
        CleanupOpts(execute=True, yes_safe=True),
    )
    confirmation = next(events)
    assert isinstance(confirmation, ConfirmRequired)
    assert confirmation.total_bytes == allocation


def test_external_hardlink_is_not_claimed_as_reclaimable(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    outside = tmp_path / "outside"
    selected.mkdir()
    outside.mkdir()
    source = selected / "shared.bin"
    source.write_bytes(b"x" * 4096)
    os.link(source, outside / "shared.bin")

    report = _scan([_path_entry(selected, "selected")])

    assert report.entries[0].reclaimable_bytes == 0
    assert report.total_reclaimable_bytes() == 0


def test_overlapping_entries_do_not_double_count_complete_hardlinks(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "one.bin"
    source.write_bytes(b"x" * 4096)
    os.link(source, root / "two.bin")

    report = _scan([_path_entry(root, "one"), _path_entry(root, "two")])
    allocation = report.entries[0].footprint_bytes

    assert allocation is not None and allocation > 0
    assert report.total_footprint_bytes() == allocation
    assert report.total_reclaimable_bytes() == allocation


def test_typed_actions_and_usage_round_trip_through_snapshot() -> None:
    path = Path("/tmp/cache with spaces")
    entry = Entry(
        provider="typed",
        id="typed:cache",
        path=path,
        label="cache",
        size_bytes=100,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=[],
        usage=DiskUsage(100, 80, 20),
        actions=(
            DeletePathAction(path),
            CommandAction(("tool", "arg with spaces")),
            AdviceAction("review first"),
        ),
    )
    report = Report(
        entries=[entry],
        scanned_at=datetime(2026, 9, 5, tzinfo=UTC),
        hostname="host",
        platform="darwin",
    )

    restored = Report.from_json(report.to_json())

    assert restored.entries[0].usage == DiskUsage(100, 80, 20)
    assert restored.entries[0].actions == entry.actions
    assert restored.entries[0].recipe_lines() == [
        "rm -rf -- '/tmp/cache with spaces'",
        "tool 'arg with spaces'",
        "echo 'review first'",
    ]
