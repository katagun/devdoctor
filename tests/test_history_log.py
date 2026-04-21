import json
from pathlib import Path

from diskdoctor.history_log import append_event, read_events


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
