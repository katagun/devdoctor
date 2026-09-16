from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from devdoctor.web.app import build_app
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
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
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


def test_dashboard_disk_summary_carries_reclaimable_and_footprint_totals(
    tmp_path, monkeypatch
) -> None:
    """#102: the mapper dropped the usage totals storage already saves, so the
    dashboard fell back to the footprint and showed it as "estimated reclaimable"."""
    client = _client(tmp_path, monkeypatch)
    scan = client.get("/api/scan", headers={"Host": "testserver"}).json()

    body = client.get("/api/dashboard/disk-summary", headers={"Host": "testserver"}).json()

    assert body["total_reclaimable_bytes"] == scan["total_reclaimable_bytes"]
    assert body["total_footprint_bytes"] == scan["total_footprint_bytes"]
    assert body["total_shared_bytes"] == scan["total_shared_bytes"]
    assert body["unknown_reclaimable_entries"] == scan["unknown_reclaimable_entries"]
    scan_by_id = {entry["id"]: entry for entry in scan["entries"]}
    for entry in body["entries"]:
        for key in ("footprint_bytes", "reclaimable_bytes", "shared_bytes"):
            assert entry[key] == scan_by_id[entry["id"]][key], (entry["id"], key)
    (sample,) = [t for t in body["provider_totals"] if t["provider"] == "sample-cache"]
    assert sample["footprint_bytes"] == 512
    assert sample["reclaimable_bytes"] == 512
