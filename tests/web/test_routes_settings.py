from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from devdoctor.config import load_app_settings
from devdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)


def test_get_settings_returns_default_filesystem_backend(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    resp = client.get("/api/settings", headers={"Host": "testserver"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["storage_backend"] == "filesystem"
    assert body["available_backends"] == ["filesystem", "sqlite"]


def test_patch_settings_switches_to_sqlite_and_persists(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sqlite_path = tmp_path / "state" / "devdoctor.sqlite3"

    resp = client.patch(
        "/api/settings",
        json={"storage_backend": "sqlite", "sqlite_path": str(sqlite_path)},
        headers={"Host": "testserver"},
    )

    assert resp.status_code == 200
    assert resp.json()["storage_backend"] == "sqlite"
    assert sqlite_path.is_file()
    assert load_app_settings().storage_backend == "sqlite"


def test_patch_settings_rejects_unwritable_sqlite_path(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    bad_dir = tmp_path / "not-dir"
    bad_dir.write_text("not a directory")
    bad_path = bad_dir / "state.sqlite3"

    resp = client.patch(
        "/api/settings",
        json={"storage_backend": "sqlite", "sqlite_path": str(bad_path)},
        headers={"Host": "testserver"},
    )

    assert resp.status_code == 400
