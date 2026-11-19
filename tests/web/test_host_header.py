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


def _write_app() -> FastAPI:
    app = _app({"127.0.0.1:8731", "localhost:8731"})

    @app.post("/api/act")
    def act():
        return {"ok": True}

    return app


def _post(headers: dict[str, str]):
    return TestClient(_write_app()).post("/api/act", headers={"Host": "127.0.0.1:8731", **headers})


def test_an_api_request_from_another_origin_is_refused():
    """A page on any other site (or another local port) must not drive the API
    through the user's browser: this server deletes files and kills processes."""
    r = _post({"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "bad_origin"
    assert _post({"Origin": "http://localhost:3000"}).status_code == 403
    assert _post({"Origin": "null"}).status_code == 403


def test_an_api_request_the_browser_marks_cross_site_is_refused():
    assert _post({"Sec-Fetch-Site": "cross-site"}).status_code == 403
    # Another port on localhost is "same-site" to a browser, and still not this app.
    assert _post({"Sec-Fetch-Site": "same-site"}).status_code == 403


def test_the_apps_own_page_and_non_browser_clients_are_allowed():
    assert (
        _post({"Origin": "http://127.0.0.1:8731", "Sec-Fetch-Site": "same-origin"}).status_code
        == 200
    )
    assert _post({"Origin": "http://localhost:8731"}).status_code == 200
    assert _post({}).status_code == 200


def test_opening_the_ui_from_a_link_on_another_site_still_works():
    client = TestClient(_write_app())
    r = client.get(
        "/index.html", headers={"Host": "127.0.0.1:8731", "Sec-Fetch-Site": "cross-site"}
    )
    assert r.status_code == 200
