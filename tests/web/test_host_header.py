from fastapi import FastAPI
from starlette.testclient import TestClient

from devdoctor.web.middleware import HostHeaderMiddleware


def _app(allowed_hosts: set[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(HostHeaderMiddleware, allowed_hosts=allowed_hosts)

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    @app.get("/index.html")
    def index():
        return {"ok": True}

    return app


def test_matching_host_header_allowed():
    client = TestClient(_app({"127.0.0.1:8731", "localhost:8731"}))
    r = client.get("/api/ping", headers={"Host": "127.0.0.1:8731"})
    assert r.status_code == 200


def test_mismatched_host_header_rejected_on_api():
    client = TestClient(_app({"127.0.0.1:8731"}))
    r = client.get("/api/ping", headers={"Host": "evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "bad_host"


def test_static_route_is_also_protected():
    # Defense in depth: even static files should reject mismatched hosts.
    client = TestClient(_app({"127.0.0.1:8731"}))
    r = client.get("/index.html", headers={"Host": "evil.example.com"})
    assert r.status_code == 403


def test_localhost_variant_allowed_when_configured():
    client = TestClient(_app({"127.0.0.1:8731", "localhost:8731"}))
    r = client.get("/api/ping", headers={"Host": "localhost:8731"})
    assert r.status_code == 200
