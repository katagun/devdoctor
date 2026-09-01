from pathlib import Path

from starlette.testclient import TestClient

from devdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
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


def test_disk_scan_alias_returns_report_json(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/disk/scan", headers={"Host": "testserver"})
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert "scanned_at" in body


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
    from devdoctor import history

    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/scan", headers={"Host": "testserver"})
    assert resp.status_code == 200
    snapshot_dir = history.default_snapshot_dir()
    assert not snapshot_dir.exists() or list(snapshot_dir.glob("*.json")) == []


def test_scan_with_snapshot_flag_writes_auto(tmp_path, monkeypatch) -> None:
    from devdoctor import history

    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/scan?snapshot=true", headers={"Host": "testserver"})
    assert resp.status_code == 200
    files = list(history.default_snapshot_dir().glob("*.json"))
    assert len(files) == 1
    assert files[0].name.endswith("--auto.json")


def test_scan_skips_auto_snapshot_inside_min_interval(tmp_path, monkeypatch) -> None:
    """Filter-chip changes on the disk page send `snapshot=true` on every fetch.
    Without server-side rate limiting, a daily-cadence user would still see
    one auto-snapshot per click. The min-interval param is the cadence."""
    from devdoctor import history

    client = _client(tmp_path, monkeypatch)
    snapshot_dir = history.default_snapshot_dir()
    # First call: writes (no prior auto-snapshot exists).
    r1 = client.get(
        "/api/scan?snapshot=true&snapshot_min_interval_ms=86400000",
        headers={"Host": "testserver"},
    )
    assert r1.status_code == 200
    assert len(list(snapshot_dir.glob("*--auto.json"))) == 1

    # Second call moments later with daily interval (86,400,000 ms): skipped.
    r2 = client.get(
        "/api/scan?snapshot=true&snapshot_min_interval_ms=86400000",
        headers={"Host": "testserver"},
    )
    assert r2.status_code == 200
    assert len(list(snapshot_dir.glob("*--auto.json"))) == 1


def test_scan_writes_auto_snapshot_when_min_interval_zero(tmp_path, monkeypatch) -> None:
    """Live cadence (staleTime=0) opts out of rate-limiting — every scan should
    still record. Backward-compat with the no-param case."""
    from devdoctor import history

    client = _client(tmp_path, monkeypatch)
    snapshot_dir = history.default_snapshot_dir()
    for _ in range(3):
        client.get(
            "/api/scan?snapshot=true&snapshot_min_interval_ms=0",
            headers={"Host": "testserver"},
        )
    assert len(list(snapshot_dir.glob("*--auto.json"))) == 3


def test_scan_with_snapshot_flag_prunes_to_retention(tmp_path, monkeypatch) -> None:
    from datetime import UTC, datetime

    from devdoctor import history
    from devdoctor.types import ProviderTiming, Report, SnapshotKind

    monkeypatch.setattr(history, "AUTO_SNAPSHOT_RETENTION", 3)
    client = _client(tmp_path, monkeypatch)
    snapshot_dir = history.default_snapshot_dir()

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
        history.write_snapshot(r, snapshot_dir)

    resp = client.get("/api/scan?snapshot=true", headers={"Host": "testserver"})
    assert resp.status_code == 200
    remaining = sorted(p.name for p in snapshot_dir.glob("*--auto.json"))
    # 5 seeded + 1 new = 6; prune(keep=3) leaves 3.
    assert len(remaining) == 3
