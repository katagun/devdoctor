from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "blob.bin").write_bytes(b"x" * 512)
    yaml = tmp_path / "paths.yaml"
    yaml.write_text(
        f"""- name: sample-cache
  description: sample
  risk: safe
  platforms: [darwin, linux]
  paths: [{cache_dir}]
  recipe: "rm -rf {{path}}"
"""
    )
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)


def test_dashboard_disk_summary_returns_null_before_scan(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    resp = client.get("/api/dashboard/disk-summary", headers={"Host": "testserver"})

    assert resp.status_code == 200
    assert resp.json() is None


def test_scan_updates_dashboard_disk_summary(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    scan = client.get("/api/scan", headers={"Host": "testserver"})
    assert scan.status_code == 200

    resp = client.get("/api/dashboard/disk-summary", headers={"Host": "testserver"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_bytes"] >= 512
    assert body["entry_count"] >= 1
    assert any(entry["provider"] == "sample-cache" for entry in body["entries"])
    assert any(total["provider"] == "sample-cache" for total in body["provider_totals"])
