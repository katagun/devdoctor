from datetime import UTC, datetime
from pathlib import Path

from devdoctor.cleanup import PlannedEntry
from devdoctor.cleanup_audit import all_bytes_verified, build_event, estimated_reclaimed_bytes
from devdoctor.types import CleanResult, DeletePathAction, Entry, Risk


def _entry(id_: str, size: int, provider: str = "p") -> Entry:
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[f"rm -rf /{id_}"],
    )


def _plan(*entries: Entry) -> list[PlannedEntry]:
    return [
        PlannedEntry(
            entry=e,
            actions=(DeletePathAction(e.path, recursive=True),),
            estimate_bytes=e.size_bytes,
        )
        for e in entries
    ]


def test_build_event_keeps_the_existing_keys_and_adds_the_new_ones() -> None:
    a, b, c = _entry("a", 100), _entry("b", 200), _entry("c", 300)
    results = [
        CleanResult(entry_id="a", status="ok", freed_bytes=100, message="cleanup succeeded"),
        CleanResult(entry_id="b", status="error", freed_bytes=0, message="rm: boom"),
        CleanResult(entry_id="c", status="skipped", freed_bytes=0, message="declined"),
    ]
    at = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)

    event = build_event(
        results,
        "ok",
        source="cli",
        plan=_plan(a, b),
        entries=[a, b, c],
        free_before=10_000,
        free_after=10_100,
        now=at,
    )

    assert event["type"] == "cleanup"
    assert event["source"] == "cli"
    assert event["job_id"] is None
    assert event["outcome"] == "ok"
    assert event["at"] == "2026-09-16T13:00:00+00:00"
    assert event["total_freed_bytes"] == 100
    assert event["total_estimated_reclaimed_bytes"] == 100
    assert event["bytes_verified"] is False
    assert event["free_before_bytes"] == 10_000
    assert event["free_after_bytes"] == 10_100
    assert event["plan"] == [
        {
            "entry_id": "a",
            "provider": "p",
            "label": "p/a",
            "path": "/a",
            "risk": "safe",
            "estimate_bytes": 100,
            "actions": ["rm -rf -- /a"],
        },
        {
            "entry_id": "b",
            "provider": "p",
            "label": "p/b",
            "path": "/b",
            "risk": "safe",
            "estimate_bytes": 200,
            "actions": ["rm -rf -- /b"],
        },
    ]
    assert event["results"][1] == {
        "entry_id": "b",
        "status": "error",
        "freed_bytes": 0,
        "message": "rm: boom",
        "bytes_verified": False,
        "provider": "p",
        "label": "p/b",
        "path": "/b",
    }
    assert "error" not in event


def test_build_event_for_a_web_run_carries_job_id_and_error() -> None:
    a = _entry("a", 100)
    event = build_event([], "error", source="web", plan=[], entries=[a], job_id="abc", error="boom")
    assert (event["source"], event["job_id"], event["error"]) == ("web", "abc", "boom")
    assert event["free_before_bytes"] is None and event["free_after_bytes"] is None
    assert event["plan"] == [] and event["results"] == []


def test_totals_count_only_successful_entries() -> None:
    a, b = _entry("a", 100), _entry("b", 200)
    results = [
        CleanResult(entry_id="a", status="ok", freed_bytes=100, bytes_verified=True),
        CleanResult(entry_id="b", status="error", freed_bytes=0),
    ]
    assert estimated_reclaimed_bytes([a, b], results) == 100
    assert all_bytes_verified(results) is True
    assert all_bytes_verified([CleanResult(entry_id="b", status="error", freed_bytes=0)]) is False


def test_free_bytes_reports_the_volume_even_when_home_does_not_exist() -> None:
    # tests/conftest.py pins HOME to a directory that is never created; the walk
    # up to the nearest existing ancestor is what makes this an int, not None.
    from devdoctor import cleanup_audit

    free = cleanup_audit.free_bytes()
    assert isinstance(free, int) and free > 0


def test_free_space_lagged_when_the_disk_released_under_half_of_what_was_deleted() -> None:
    from devdoctor import cleanup_audit

    # 18.1 GB deleted, 100 MB released: local snapshots are holding the blocks.
    assert cleanup_audit.free_space_lagged(35_800_000_000, 35_900_000_000, 18_100_000_000)


def test_free_space_not_lagged_at_or_above_half() -> None:
    from devdoctor import cleanup_audit

    assert not cleanup_audit.free_space_lagged(1_000_000_000, 1_350_000_000, 700_000_000)
    assert not cleanup_audit.free_space_lagged(1_000_000_000, 1_700_000_000, 700_000_000)


def test_free_space_lagged_needs_both_measurements_and_something_deleted() -> None:
    from devdoctor import cleanup_audit

    assert not cleanup_audit.free_space_lagged(None, 1_000, 1_000_000_000)
    assert not cleanup_audit.free_space_lagged(1_000, None, 1_000_000_000)
    assert not cleanup_audit.free_space_lagged(1_000, 1_000, 0)


def test_free_space_lagged_ignores_cleanups_too_small_to_measure() -> None:
    from devdoctor import cleanup_audit

    # Other processes write tens of megabytes between the two measurements, so a
    # 50 MB cleanup whose delta reads as zero is noise, not a held snapshot.
    assert not cleanup_audit.free_space_lagged(1_000_000_000, 1_000_000_000, 50_000_000)
    assert cleanup_audit.free_space_lagged(1_000_000_000, 1_000_000_000, 100_000_000)
