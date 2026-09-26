import asyncio
import json
import socket
import threading
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from devdoctor.web.app import build_app
from tests.conftest import FakeShell
from tests.web.sse_server import run_server


def _build(tmp_path: Path, monkeypatch, *, extra_hosts: set[str] | None = None):
    yaml = tmp_path / "paths.yaml"
    # A PathProvider whose path exists -> one Entry in the scan. The recipe must
    # be a real "rm -rf {path}" so it resolves to a DeletePathAction: any other
    # command is parsed as advice and never emits execute_start.
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "f").write_bytes(b"x" * 100)
    yaml.write_text(
        "- name: t\n"
        "  description: t\n"
        "  risk: safe\n"
        "  platforms: [darwin, linux]\n"
        f"  paths: [{tmp_path}/cache]\n"
        "  recipe: 'rm -rf {path}'\n"
    )
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    hosts = {"testserver"} | (extra_hosts or set())
    return build_app(shell, allowed_hosts=hosts, static_dir=tmp_path)


def _build_for_port(tmp_path: Path, monkeypatch, port: int):
    return _build(tmp_path, monkeypatch, extra_hosts={f"127.0.0.1:{port}"})


def _loopback_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock


class _GatedScan:
    """A scan that takes as long as the test wants: it blocks until released.

    It blocks its thread the way a real walk of a large disk does, for a minute or
    more. The timeout only stops a broken test from hanging the suite.
    """

    def __init__(self, real_scan):
        self._real_scan = real_scan
        self.calls: list[object] = []
        self._entered = threading.Event()
        self._released = threading.Event()

    def __call__(self, providers, filters, now, **kwargs):
        self.calls.append(filters.providers)
        self._entered.set()
        self._released.wait(timeout=10)
        return self._real_scan(providers, filters, now, **kwargs)

    async def entered(self) -> None:
        assert await asyncio.to_thread(self._entered.wait, 10), "the job never began its re-scan"

    def release(self) -> None:
        self._released.set()


async def _cancel_job(client: AsyncClient, started) -> None:
    if started.status_code == 200:
        await client.post(f"/api/clean/jobs/{started.json()['job_id']}/cancel")


@pytest.mark.asyncio
async def test_full_clean_job_lifecycle_via_sse(tmp_path, monkeypatch):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = _build_for_port(tmp_path, monkeypatch, port)
    base_url = f"http://127.0.0.1:{port}"

    with run_server(app, sock):
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
        entry_id = next(e["id"] for e in r.json()["entries"] if e["provider"] == "t")
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


@pytest.mark.asyncio
async def test_cleanup_job_keeps_every_selected_entry_from_an_uncontained_scan(
    tmp_path, monkeypatch
):
    from devdoctor.types import (
        CommandAction,
        DeletePathAction,
        DiskUsage,
        Entry,
        Report,
        Risk,
    )
    from devdoctor.web import routes_clean

    worktree_path = tmp_path / "wt" / "feature"

    def entry(provider, id_, path, risk, action):
        return Entry(
            provider=provider,
            id=id_,
            path=path,
            label=str(path),
            size_bytes=100,
            mtime=None,
            risk=risk,
            recipe=[],
            usage=DiskUsage(100, 100),
            actions=(action,),
        )

    worktree = entry(
        "git-worktrees",
        "git-worktrees:feature",
        worktree_path,
        Risk.RECLAIMABLE,
        CommandAction(
            ("git", "-C", str(tmp_path / "app"), "worktree", "remove", str(worktree_path))
        ),
    )
    inside = entry(
        "node-project-dependencies",
        "node:inside",
        worktree_path / "node_modules",
        Risk.DANGEROUS,
        DeletePathAction(worktree_path / "node_modules"),
    )
    outside = entry(
        "node-project-dependencies",
        "node:outside",
        tmp_path / "app" / "node_modules",
        Risk.RECLAIMABLE,
        DeletePathAction(tmp_path / "app" / "node_modules"),
    )
    contain_args: list[bool] = []

    def fake_scan(providers, filters, now, *, contain=True):
        contain_args.append(contain)
        return Report(
            entries=[worktree, inside, outside], scanned_at=now, hostname="h", platform="darwin"
        )

    monkeypatch.setattr(routes_clean.discovery, "scan", fake_scan)
    app = _build(tmp_path, monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        r = await client.post(
            "/api/clean/jobs",
            json={"entry_ids": ["node:inside", "git-worktrees:feature", "node:outside"]},
            headers={"Host": "testserver"},
        )
        assert r.status_code == 200
        runner = app.state.runner_registry.active()
        assert [e.id for e in runner.report.entries] == [
            "git-worktrees:feature",
            "node:inside",
            "node:outside",
        ]
        await runner.cancel()
    assert contain_args == [False]


@pytest.mark.asyncio
async def test_cleanup_rescans_only_the_providers_the_selection_names(tmp_path, monkeypatch):
    """#92: a job for one cache used to re-run every provider before it could start."""
    from devdoctor.web import routes_clean

    app = _build(tmp_path, monkeypatch)
    real_scan = routes_clean.discovery.scan
    seen: list[frozenset[str] | None] = []

    def spy(providers, filters, now, **kwargs):
        seen.append(filters.providers)
        return real_scan(providers, filters, now, **kwargs)

    monkeypatch.setattr(routes_clean.discovery, "scan", spy)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        r = await client.post(
            "/api/clean/jobs",
            json={"entry_ids": [f"t:{tmp_path}/cache"]},
            headers={"Host": "testserver"},
        )
        assert r.status_code == 200, r.text
        await app.state.runner_registry.active().cancel()
    assert seen == [frozenset({"t"})]


@pytest.mark.asyncio
async def test_an_id_no_provider_owns_falls_back_to_a_full_rescan(tmp_path, monkeypatch):
    from devdoctor.web import routes_clean

    app = _build(tmp_path, monkeypatch)
    real_scan = routes_clean.discovery.scan
    seen: list[frozenset[str] | None] = []

    def spy(providers, filters, now, **kwargs):
        seen.append(filters.providers)
        return real_scan(providers, filters, now, **kwargs)

    monkeypatch.setattr(routes_clean.discovery, "scan", spy)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        r = await client.post(
            "/api/clean/jobs",
            json={"entry_ids": [f"t:{tmp_path}/cache", "bare-legacy-id"]},
            headers={"Host": "testserver"},
        )
    assert r.status_code == 400
    assert r.json()["error"]["ids"] == ["bare-legacy-id"]
    assert seen == [None]


@pytest.mark.asyncio
async def test_the_server_answers_other_requests_while_a_job_rescans(tmp_path, monkeypatch):
    """A job's re-scan can take minutes on a large disk. It used to run on the event
    loop, so every other request waited for it: pages, scan progress, even the job's
    own event stream."""
    from devdoctor.web import routes_clean

    sock = _loopback_socket()
    port = sock.getsockname()[1]
    app = _build_for_port(tmp_path, monkeypatch, port)
    scan = _GatedScan(routes_clean.discovery.scan)
    monkeypatch.setattr(routes_clean.discovery, "scan", scan)
    body = {"entry_ids": [f"t:{tmp_path}/cache"]}

    with run_server(app, sock):
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            start = asyncio.create_task(client.post("/api/clean/jobs", json=body, timeout=15))
            try:
                await scan.entered()
                health = await client.get("/api/health", timeout=2)
            finally:
                scan.release()
                started = await start
                await _cancel_job(client, started)

    assert health.status_code == 200
    assert started.status_code == 200


@pytest.mark.asyncio
async def test_a_second_start_is_refused_at_once_while_the_first_rescans(tmp_path, monkeypatch):
    """A second click on execute used to wait out the first re-scan, run a re-scan of
    its own and only then find the slot taken: each click cost another full re-scan."""
    from devdoctor.web import routes_clean

    sock = _loopback_socket()
    port = sock.getsockname()[1]
    app = _build_for_port(tmp_path, monkeypatch, port)
    scan = _GatedScan(routes_clean.discovery.scan)
    monkeypatch.setattr(routes_clean.discovery, "scan", scan)
    body = {"entry_ids": [f"t:{tmp_path}/cache"]}

    with run_server(app, sock):
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            first = asyncio.create_task(client.post("/api/clean/jobs", json=body, timeout=15))
            try:
                await scan.entered()
                second = await client.post("/api/clean/jobs", json=body, timeout=2)
            finally:
                scan.release()
                started = await first
                await _cancel_job(client, started)

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "job_in_progress"
    assert started.status_code == 200
    assert scan.calls == [frozenset({"t"})]


@pytest.mark.asyncio
async def test_a_failed_rescan_leaves_the_slot_free(tmp_path, monkeypatch):
    """The slot is held while the job is prepared; a start that fails must give it
    back, or every later cleanup would be refused until the app restarts."""
    from devdoctor.web import routes_clean

    app = _build(tmp_path, monkeypatch)
    real_scan = routes_clean.discovery.scan

    def failing_scan(*args, **kwargs):
        raise OSError("the volume went away")

    body = {"entry_ids": [f"t:{tmp_path}/cache"]}
    monkeypatch.setattr(routes_clean.discovery, "scan", failing_scan)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        failed = await client.post("/api/clean/jobs", json=body)
        monkeypatch.setattr(routes_clean.discovery, "scan", real_scan)
        retried = await client.post("/api/clean/jobs", json=body)
        await _cancel_job(client, retried)

    assert failed.status_code == 500
    assert retried.status_code == 200, retried.text
