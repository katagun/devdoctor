import contextlib
import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def _build(tmp_path: Path, monkeypatch, *, extra_hosts: set[str] | None = None):
    yaml = tmp_path / "paths.yaml"
    # A single PathProvider whose path exists -> one Entry in the scan.
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "f").write_bytes(b"x" * 100)
    yaml.write_text(
        "- name: t\n"
        "  description: t\n"
        "  risk: safe\n"
        "  platforms: [darwin, linux]\n"
        f"  paths: [{tmp_path}/cache]\n"
        "  recipe: 'echo cleaning {path}'\n"
    )
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    hosts = {"testserver"} | (extra_hosts or set())
    return build_app(shell, allowed_hosts=hosts, static_dir=tmp_path)


def _build_for_port(tmp_path: Path, monkeypatch, port: int):
    return _build(tmp_path, monkeypatch, extra_hosts={f"127.0.0.1:{port}"})


@contextlib.contextmanager
def _run_server(app, sock: socket.socket):
    """Run uvicorn in a background thread on a pre-bound loopback socket.

    Two deliberate choices keep this deterministic and off deprecated APIs:

    - We bind the socket ourselves and hand it to uvicorn (``sockets=[sock]``),
      so there's no free-port TOCTOU — the port can't be grabbed by another
      process in the window between "find a free port" and "uvicorn binds it".
    - ``ws="none"`` stops uvicorn from importing the deprecated ``websockets``
      legacy server classes. This is an SSE test with no websockets involved,
      so we skip that machinery entirely (and its DeprecationWarnings).

    A real server (rather than httpx.ASGITransport) is still required: the
    transport buffers the whole response before returning, which can't drive
    the interactive SSE stream where the client POSTs answers between events.
    """
    config = uvicorn.Config(app, log_level="warning", lifespan="off", ws="none")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.started:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("uvicorn did not start in time")
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        with contextlib.suppress(OSError):
            sock.close()


@pytest.mark.asyncio
async def test_full_clean_job_lifecycle_via_sse(tmp_path, monkeypatch):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = _build_for_port(tmp_path, monkeypatch, port)
    base_url = f"http://127.0.0.1:{port}"

    with _run_server(app, sock):
        async with AsyncClient(base_url=base_url) as client:
            # Learn the one entry's id via /api/scan
            r = await client.get("/api/scan")
            report = r.json()
            entry_id = report["entries"][0]["id"]

            # Start the job
            r = await client.post(
                "/api/clean/jobs",
                json={"entry_ids": [entry_id]},
            )
            assert r.status_code == 200
            job_id = r.json()["job_id"]

            events_seen: list[dict] = []

            async with aconnect_sse(
                client,
                "GET",
                f"/api/clean/jobs/{job_id}/events",
                timeout=10,
            ) as es:
                async for sse in es.aiter_sse():
                    if not sse.event or sse.event == "ping":
                        continue
                    data = json.loads(sse.data)
                    events_seen.append({"event": sse.event, **data})

                    if sse.event == "prompt":
                        await client.post(
                            f"/api/clean/jobs/{job_id}/answer",
                            json={"entry_id": data["entry_id"], "choice": "y"},
                        )
                    elif sse.event == "awaiting_confirm":
                        await client.post(
                            f"/api/clean/jobs/{job_id}/confirm",
                            json={"confirmed": True},
                        )
                    elif sse.event == "done":
                        break

        kinds = [e["event"] for e in events_seen]
        assert "prompt" in kinds
        assert "awaiting_confirm" in kinds
        assert "execute_start" in kinds
        assert "execute_result" in kinds
        assert kinds[-1] == "done"


@pytest.mark.asyncio
async def test_second_concurrent_job_returns_409(tmp_path, monkeypatch):
    app = _build(tmp_path, monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        r1 = await client.post(
            "/api/clean/jobs",
            json={"entry_ids": ["nope"]},
            headers={"Host": "testserver"},
        )
        # entry_id "nope" is unknown -> 400 before the runner starts, so the
        # slot is free. We validate entry_ids against a fresh scan.
        assert r1.status_code in (400, 200)

        r = await client.get("/api/scan", headers={"Host": "testserver"})
        entry_id = r.json()["entries"][0]["id"]
        r2 = await client.post(
            "/api/clean/jobs",
            json={"entry_ids": [entry_id]},
            headers={"Host": "testserver"},
        )
        assert r2.status_code == 200

        # Second concurrent start without consuming events -> 409
        r3 = await client.post(
            "/api/clean/jobs",
            json={"entry_ids": [entry_id]},
            headers={"Host": "testserver"},
        )
        assert r3.status_code == 409


@pytest.mark.asyncio
async def test_unknown_entry_id_is_400(tmp_path, monkeypatch):
    app = _build(tmp_path, monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        r = await client.post(
            "/api/clean/jobs",
            json={"entry_ids": ["nope"]},
            headers={"Host": "testserver"},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "unknown_entry"
