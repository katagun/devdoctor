from pathlib import Path

from starlette.testclient import TestClient

from devdoctor.web.app import build_app
from tests.conftest import FakeShell


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={})
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)


def test_disk_usage_returns_plausible_numbers(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/disk-usage", headers={"Host": "testserver"})
    assert r.status_code == 200
    body = r.json()
    assert body["mount"] == "/"
    assert body["total_bytes"] > 0
    assert body["free_bytes"] >= 0
    assert body["used_bytes"] >= 0
    # used + free sums can differ slightly from total due to reserved blocks;
    # just check they fit inside the total envelope.
    assert body["used_bytes"] + body["free_bytes"] <= body["total_bytes"] + 1
