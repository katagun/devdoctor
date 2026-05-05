from pathlib import Path

from starlette.testclient import TestClient

from diskdoctor.types import ShellResult
from diskdoctor.web.app import build_app
from tests.conftest import FakeShell


def test_memory_route_returns_live_memory_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("diskdoctor.memory.collectors.system.sys.platform", "darwin")
    monkeypatch.setattr("diskdoctor.memory.discovery.sys.platform", "darwin")
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    shell = FakeShell(
        responses={
            ("sysctl", "-n", "hw.memsize"): ShellResult(0, str(16 * 1024**3), ""),
            ("vm_stat",): ShellResult(
                0,
                """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100.
Pages inactive:                           50.
Pages speculative:                        25.
Pages purgeable:                           5.
Pages occupied by compressor:             10.
""",
                "",
            ),
            ("sysctl", "vm.swapusage"): ShellResult(
                0,
                "vm.swapusage: total = 2048.00M  used = 512.00M  free = 1536.00M",
                "",
            ),
            ("ps", "-axo", "pid=,ppid=,rss=,comm="): ShellResult(
                0,
                """101 1 1048576 /Applications/Firefox.app/Contents/MacOS/firefox
102 1 524288 /Applications/Docker.app/Contents/MacOS/Docker
103 1 262144 /Applications/Slack.app/Contents/MacOS/Slack
""",
                "",
            ),
        }
    )
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/memory", headers={"Host": "testserver"})

    assert response.status_code == 200
    body = response.json()
    assert body["system"]["total_bytes"] == 16 * 1024**3
    assert body["system"]["swap_used_bytes"] == 512 * 1024**2
    assert body["consumers"][0]["name"] == "Firefox"
    assert body["consumers"][0]["kind"] == "browser"
    assert body["consumers"][1]["kind"] == "docker"
    assert body["consumers"][2]["kind"] == "electron"
    totals = {row["id"]: row for row in body["provider_totals"]}
    assert totals["browsers"]["rss_bytes"] == 1048576 * 1024
    assert totals["docker"]["consumer_count"] == 1
    assert totals["electron-apps"]["consumer_count"] == 1
    assert {s["id"] for s in body["suggestions"]} >= {"memory-pressure", "browser-memory"}


def test_memory_history_records_observation(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    response = client.get("/api/memory", headers={"Host": "testserver"})
    assert response.status_code == 200

    history = client.get("/api/memory/history", headers={"Host": "testserver"})
    assert history.status_code == 200
    rows = history.json()["observations"]
    assert len(rows) == 1
    assert rows[0]["pressure"] == "critical"
    assert rows[0]["top_consumer_name"] == "Firefox"


def test_memory_snapshots_create_list_and_diff(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    first = client.post(
        "/api/memory/snapshots",
        json={"note": "before"},
        headers={"Host": "testserver"},
    )
    second = client.post(
        "/api/memory/snapshots",
        json={"note": "after"},
        headers={"Host": "testserver"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    listing = client.get("/api/memory/snapshots", headers={"Host": "testserver"})
    assert len(listing.json()) == 2

    diff = client.get(
        f"/api/memory/snapshots/diff?from_={first.json()['name']}&to_={second.json()['name']}",
        headers={"Host": "testserver"},
    )
    assert diff.status_code == 200
    assert "available_delta_bytes" in diff.json()


def test_memory_sources_returns_current_integrations(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    response = client.get("/api/memory/sources", headers={"Host": "testserver"})

    assert response.status_code == 200
    ids = {source["id"] for source in response.json()}
    assert {"system-memory", "process-table", "browser-bridge"} <= ids


def test_memory_providers_return_selectable_process_categories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    response = client.get("/api/memory/providers", headers={"Host": "testserver"})

    assert response.status_code == 200
    ids = {provider["id"] for provider in response.json()}
    assert {"browsers", "electron-apps", "docker", "local-llms"} <= ids


def test_memory_route_filters_by_selected_provider(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    response = client.get(
        "/api/memory?provider=electron-apps&record=false",
        headers={"Host": "testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [consumer["kind"] for consumer in body["consumers"]] == ["electron"]
    totals = {row["id"]: row for row in body["provider_totals"]}
    assert totals["electron-apps"]["selected"] is True
    assert totals["browsers"]["selected"] is False
    assert {suggestion["id"] for suggestion in body["suggestions"]} >= {"electron-memory"}


def test_memory_route_rejects_unknown_provider(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    response = client.get(
        "/api/memory?provider=missing&record=false",
        headers={"Host": "testserver"},
    )

    assert response.status_code == 422


def test_memory_workloads_and_plan(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    workloads = client.get("/api/memory/workloads", headers={"Host": "testserver"})
    assert workloads.status_code == 200
    assert {w["id"] for w in workloads.json()} >= {"llm-7b", "docker-dev"}

    plan = client.post(
        "/api/memory/plan",
        json={"workload_id": "llm-7b", "safety_margin_bytes": 0},
        headers={"Host": "testserver"},
    )

    assert plan.status_code == 200
    body = plan.json()
    assert body["workload"]["id"] == "llm-7b"
    assert body["required_bytes"] > 0
    assert "fits_now" in body
    assert "actions" in body


def test_memory_plan_supports_custom_workload(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    plan = client.post(
        "/api/memory/plan",
        json={"custom_label": "Huge compile", "custom_required_bytes": 64 * 1024**3},
        headers={"Host": "testserver"},
    )

    assert plan.status_code == 200
    body = plan.json()
    assert body["workload"]["label"] == "Huge compile"
    assert body["fits_now"] is False
    assert body["remaining_deficit_bytes"] > 0


def test_memory_action_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    client = _memory_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/memory/actions",
        json={
            "id": "stop-docker",
            "kind": "stop_service",
            "target_id": "docker",
            "confirmed": False,
        },
        headers={"Host": "testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "confirmation" in body["message"]


def test_memory_action_can_quit_docker_on_macos(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("diskdoctor.memory.actions.sys.platform", "darwin")
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    shell = FakeShell(
        responses={
            ("osascript", "-e", 'tell application "Docker" to quit'): ShellResult(0, "", ""),
        },
        which_table={"osascript": "/usr/bin/osascript"},
    )
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/memory/actions",
        json={
            "id": "stop-docker",
            "kind": "stop_service",
            "target_id": "docker",
            "label": "Stop Docker if idle",
            "estimated_bytes": 1234,
            "risk": "reclaimable",
            "confirmed": True,
        },
        headers={"Host": "testserver"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert shell.calls == [("osascript", "-e", 'tell application "Docker" to quit')]

    history = client.get("/api/history", headers={"Host": "testserver"})
    assert history.status_code == 200
    events = history.json()["events"]
    action_events = [event for event in events if event["type"] == "memory_action"]
    assert len(action_events) == 1
    assert action_events[0]["action_id"] == "stop-docker"
    assert action_events[0]["label"] == "Stop Docker if idle"
    assert action_events[0]["estimated_bytes"] == 1234
    assert action_events[0]["status"] == "ok"


def _memory_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr("diskdoctor.memory.collectors.system.sys.platform", "darwin")
    monkeypatch.setattr("diskdoctor.memory.discovery.sys.platform", "darwin")
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    shell = FakeShell(
        responses={
            ("sysctl", "-n", "hw.memsize"): ShellResult(0, str(16 * 1024**3), ""),
            ("vm_stat",): ShellResult(
                0,
                """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100.
Pages inactive:                           50.
Pages speculative:                        25.
Pages purgeable:                           5.
Pages occupied by compressor:             10.
""",
                "",
            ),
            ("sysctl", "vm.swapusage"): ShellResult(
                0,
                "vm.swapusage: total = 2048.00M  used = 512.00M  free = 1536.00M",
                "",
            ),
            ("ps", "-axo", "pid=,ppid=,rss=,comm="): ShellResult(
                0,
                """101 1 1048576 /Applications/Firefox.app/Contents/MacOS/firefox
102 1 524288 /Applications/Docker.app/Contents/MacOS/Docker
103 1 262144 /Applications/Slack.app/Contents/MacOS/Slack
""",
                "",
            ),
        },
        which_table={"docker": "/usr/local/bin/docker", "ollama": None},
    )
    app = build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)
    return TestClient(app)
