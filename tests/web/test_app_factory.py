from pathlib import Path

from starlette.testclient import TestClient

from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def test_build_app_returns_fastapi_with_static_mount(tmp_path: Path):
    # Build the app with a custom static dir so we don't depend on the
    # packaged placeholder.
    (tmp_path / "index.html").write_text("<!doctype html><title>test</title>")
    app = build_app(FakeShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
    client = TestClient(app)

    r = client.get("/", headers={"Host": "testserver"})
    assert r.status_code == 200
    assert "test" in r.text


def test_spa_catch_all_serves_index_for_unknown_paths(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    app = build_app(FakeShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
    client = TestClient(app)

    r = client.get("/some/client-route", headers={"Host": "testserver"})
    assert r.status_code == 200
    assert "spa" in r.text


def test_api_route_not_shadowed_by_static(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>")
    app = build_app(FakeShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/api/ping", headers={"Host": "testserver"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_health_route_supports_desktop_readiness(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>")
    app = build_app(FakeShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
    client = TestClient(app)

    r = client.get("/api/health", headers={"Host": "testserver"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app": "DevDoctor", "version": "0.1.0"}


def test_unknown_api_route_is_404_not_spa(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>")
    app = build_app(FakeShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
    client = TestClient(app)

    r = client.get("/api/nope", headers={"Host": "testserver"})
    assert r.status_code == 404
