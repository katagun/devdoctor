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
