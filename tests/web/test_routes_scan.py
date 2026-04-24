from pathlib import Path

from starlette.testclient import TestClient

from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)


def test_scan_returns_report_json(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/scan", headers={"Host": "testserver"})
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert "scanned_at" in body
    assert isinstance(body["entries"], list)


def test_scan_respects_risk_filter(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/scan?risk=safe", headers={"Host": "testserver"})
    assert r.status_code == 200


def test_scan_bad_risk_is_422(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/scan?risk=maybe", headers={"Host": "testserver"})
    assert r.status_code == 422


def test_scan_min_size_parsed(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/scan?min_size=100M", headers={"Host": "testserver"})
    assert r.status_code == 200


def test_providers_lists_registered(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/providers", headers={"Host": "testserver"})
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert {"ollama", "docker", "lm-studio-models", "huggingface-hub"} <= names


def test_recipe_returns_commented_script(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/recipe", json={}, headers={"Host": "testserver"})
    assert r.status_code == 200
    body = r.json()
    assert body["script"].startswith("#!/usr/bin/env bash")


def test_recipe_respects_provider_filter(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/api/recipe",
        json={"providers": ["ollama"]},
        headers={"Host": "testserver"},
    )
    assert r.status_code == 200


def test_scan_without_snapshot_flag_writes_nothing(tmp_path, monkeypatch) -> None:
    from diskdoctor import history

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)

    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/scan", headers={"Host": "testserver"})
    assert resp.status_code == 200
    assert list(tmp_path.glob("*.json")) == []


def test_scan_with_snapshot_flag_writes_auto(tmp_path, monkeypatch) -> None:
    from diskdoctor import history

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)

    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/scan?snapshot=true", headers={"Host": "testserver"})
    assert resp.status_code == 200
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert files[0].name.endswith("--auto.json")


def test_scan_with_snapshot_flag_prunes_to_retention(tmp_path, monkeypatch) -> None:
    from datetime import UTC, datetime

    from diskdoctor import history
    from diskdoctor.types import ProviderTiming, Report, SnapshotKind

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)
    monkeypatch.setattr(history, "AUTO_SNAPSHOT_RETENTION", 3)

    # Seed 5 existing auto-snapshots.
    for i in range(5):
        ts = datetime(2026, 4, 24, 10, 0, i, tzinfo=UTC)
        r = Report(
            entries=[],
            scanned_at=ts,
            hostname="h",
            platform="darwin",
            kind=SnapshotKind.AUTO,
            started_at=ts,
            duration_ms=10,
            per_provider=[ProviderTiming("p", 0, 0, 10)],
        )
        history.write_snapshot(r, tmp_path)

    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/scan?snapshot=true", headers={"Host": "testserver"})
    assert resp.status_code == 200
    remaining = sorted(p.name for p in tmp_path.glob("*--auto.json"))
    # 5 seeded + 1 new = 6; prune(keep=3) leaves 3.
    assert len(remaining) == 3
