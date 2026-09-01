import json
from pathlib import Path

from devdoctor.history_log import append_event, read_events


def test_append_and_read_roundtrip(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    append_event({"type": "cleanup", "job_id": "a"}, log)
    append_event({"type": "cleanup", "job_id": "b"}, log)

    events = read_events(log)
    assert [e["job_id"] for e in events] == ["b", "a"]  # newest first
    # append_event injects `at` if missing.
    assert all("at" in e for e in events)


def test_append_preserves_caller_at(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    append_event({"type": "cleanup", "at": "2026-01-01T00:00:00+00:00"}, log)
    events = read_events(log)
    assert events[0]["at"] == "2026-01-01T00:00:00+00:00"


def test_read_missing_file_returns_empty(tmp_path: Path):
    assert read_events(tmp_path / "absent.jsonl") == []


def test_read_skips_malformed_lines(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    log.write_text(
        '{"type": "cleanup", "job_id": "ok"}\nnot-json\n{"type": "cleanup", "job_id": "ok2"}\n'
    )
    events = read_events(log)
    assert [e["job_id"] for e in events] == ["ok2", "ok"]


def test_read_respects_limit(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    for i in range(5):
        append_event({"type": "cleanup", "job_id": str(i)}, log)
    events = read_events(log, limit=2)
    assert [e["job_id"] for e in events] == ["4", "3"]


def test_append_is_line_atomic(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    append_event({"type": "cleanup", "job_id": "x"}, log)
    # File ends with a newline so subsequent appends don't concatenate lines.
    content = log.read_text()
    assert content.endswith("\n")
    assert len(content.splitlines()) == 1
    parsed = json.loads(content.splitlines()[0])
    assert parsed["job_id"] == "x"


def test_event_stamps_schema_version(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    append_event({"type": "cleanup", "job_id": "x"}, log)
    parsed = json.loads(log.read_text().splitlines()[0])
    assert parsed["schema_version"] == 1


def test_append_preserves_caller_schema_version(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    append_event({"type": "cleanup", "schema_version": 99}, log)
    parsed = json.loads(log.read_text().splitlines()[0])
    assert parsed["schema_version"] == 99


def test_rotates_when_live_file_exceeds_max(tmp_path: Path, monkeypatch):
    # Shrink the rotation threshold so the test stays fast.
    monkeypatch.setattr("devdoctor.history_log.MAX_LOG_BYTES", 200)
    log = tmp_path / "audit.jsonl"
    # Three ~120-byte events — the third crosses the 200B threshold, so the
    # rotation check at the start of append_event moves the existing 2-line
    # file to audit.1.jsonl and starts a fresh audit.jsonl for the third.
    for i in range(3):
        append_event({"type": "cleanup", "job_id": f"job-{i:030d}"}, log)
    assert log.exists()
    assert (tmp_path / "audit.1.jsonl").exists()
    # Live file has only the most recent event after rotation.
    live = [json.loads(line) for line in log.read_text().splitlines()]
    rotated = [json.loads(line) for line in (tmp_path / "audit.1.jsonl").read_text().splitlines()]
    assert [e["job_id"] for e in live] == ["job-" + "2".rjust(30, "0")]
    assert [e["job_id"] for e in rotated] == [
        "job-" + "0".rjust(30, "0"),
        "job-" + "1".rjust(30, "0"),
    ]


def test_read_events_merges_across_rotations(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("devdoctor.history_log.MAX_LOG_BYTES", 200)
    log = tmp_path / "audit.jsonl"
    for i in range(5):
        append_event({"type": "cleanup", "job_id": f"job-{i:030d}"}, log)
    events = read_events(log)
    # Newest-first across live + rotations.
    assert [e["job_id"] for e in events] == [
        "job-" + "4".rjust(30, "0"),
        "job-" + "3".rjust(30, "0"),
        "job-" + "2".rjust(30, "0"),
        "job-" + "1".rjust(30, "0"),
        "job-" + "0".rjust(30, "0"),
    ]


def test_read_events_stops_early_when_limit_satisfied(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("devdoctor.history_log.MAX_LOG_BYTES", 200)
    log = tmp_path / "audit.jsonl"
    for i in range(5):
        append_event({"type": "cleanup", "job_id": f"job-{i:030d}"}, log)
    # limit=1 is satisfied by the live file alone.
    events = read_events(log, limit=1)
    assert [e["job_id"] for e in events] == ["job-" + "4".rjust(30, "0")]


def test_oldest_rotation_is_dropped(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("devdoctor.history_log.MAX_LOG_BYTES", 120)
    monkeypatch.setattr("devdoctor.history_log.KEEP_ROTATIONS", 2)
    log = tmp_path / "audit.jsonl"
    # Each line is >120B so every append triggers a rotation. After 4
    # rotations the first event should have fallen off the end.
    for i in range(5):
        append_event({"type": "cleanup", "job_id": f"j{i:100d}"}, log)
    assert log.exists()
    assert (tmp_path / "audit.1.jsonl").exists()
    assert (tmp_path / "audit.2.jsonl").exists()
    # The 3rd rotation slot must not exist — we only keep KEEP_ROTATIONS=2.
    assert not (tmp_path / "audit.3.jsonl").exists()
