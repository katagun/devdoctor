from pathlib import Path

from starlette.testclient import TestClient

from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)


def test_snapshot_create_and_list(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/snapshots", json={"note": "hello"}, headers={"Host": "testserver"})
    assert r.status_code == 200
    assert "name" in r.json()

    r2 = client.get("/api/snapshots", headers={"Host": "testserver"})
    assert r2.status_code == 200
    items = r2.json()
    assert len(items) == 1
    assert items[0]["note"] == "hello"


def test_snapshot_get_returns_report(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/snapshots", json={}, headers={"Host": "testserver"}).json()

    r = client.get(f"/api/snapshots/{created['name']}", headers={"Host": "testserver"})
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert "scanned_at" in body


def test_snapshot_missing_returns_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/snapshots/does-not-exist.json", headers={"Host": "testserver"})
    assert r.status_code == 404


def test_diff_two_snapshots(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = client.post(
        "/api/snapshots", json={"note": "before"}, headers={"Host": "testserver"}
    ).json()
    b = client.post("/api/snapshots", json={"note": "after"}, headers={"Host": "testserver"}).json()

    r = client.get(
        f"/api/diff?from_={a['name']}&to_={b['name']}",
        headers={"Host": "testserver"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body


def test_diff_live_compares_against_current(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = client.post(
        "/api/snapshots", json={"note": "before"}, headers={"Host": "testserver"}
    ).json()

    r = client.get(f"/api/diff?from_={a['name']}&to_=live", headers={"Host": "testserver"})
    assert r.status_code == 200


def test_history_includes_snapshot_events(tmp_path, monkeypatch):
    from diskdoctor.history import default_snapshot_dir

    client = _client(tmp_path, monkeypatch)
    # Pre-seed two snapshots with distinct filenames — POSTing twice in-process
    # would race on the second-precision filename stamp.
    snapshot_dir = default_snapshot_dir()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "2026-01-01T00-00-00.json").write_text(
        '{"scanned_at": "2026-01-01T00:00:00+00:00", "hostname": "h", "platform": "darwin", '
        '"entries": [], "skipped_paths": [], "note": "first"}'
    )
    (snapshot_dir / "2026-01-02T00-00-00.json").write_text(
        '{"scanned_at": "2026-01-02T00:00:00+00:00", "hostname": "h", "platform": "darwin", '
        '"entries": [], "skipped_paths": [], "note": "second"}'
    )

    r = client.get("/api/history", headers={"Host": "testserver"})
    assert r.status_code == 200
    events = r.json()["events"]
    snapshot_events = [e for e in events if e["type"] == "snapshot"]
    assert len(snapshot_events) == 2
    notes = {e["note"] for e in snapshot_events}
    assert notes == {"first", "second"}
    # Newest first.
    assert snapshot_events[0]["note"] == "second"


def test_history_includes_audit_log_cleanup_events(tmp_path, monkeypatch):
    from diskdoctor import history_log

    client = _client(tmp_path, monkeypatch)
    # Append must happen AFTER _client() sets XDG_DATA_HOME so the log lands
    # in the test's isolated audit dir.
    history_log.append_event(
        {
            "type": "cleanup",
            "job_id": "job-123",
            "outcome": "ok",
            "total_freed_bytes": 4096,
            "results": [
                {"entry_id": "e1", "status": "ok", "freed_bytes": 4096, "message": None},
            ],
        }
    )

    r = client.get("/api/history", headers={"Host": "testserver"})
    assert r.status_code == 200
    events = r.json()["events"]
    cleanup = [e for e in events if e["type"] == "cleanup"]
    assert len(cleanup) == 1
    assert cleanup[0]["job_id"] == "job-123"
    assert cleanup[0]["total_freed_bytes"] == 4096
