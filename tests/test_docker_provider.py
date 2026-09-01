import json

from devdoctor.providers.docker import DockerProvider
from devdoctor.types import Risk, ShellResult
from tests.conftest import FakeShell

_DOCKER_DF_JSON = json.dumps(
    {
        "Images": [
            {"Repository": "python", "Tag": "3.12", "Size": "200MB", "Reclaimable": "100MB (50%)"}
        ],
        "Containers": [{"Names": "web", "Size": "0B", "Reclaimable": "0B"}],
        "Volumes": [{"Name": "pgdata", "Size": "5GB", "Reclaimable": "5GB (100%)"}],
        "BuildCache": [{"Id": "x", "Size": "3GB", "Reclaimable": "3GB"}],
    }
)


def test_discover_parses_docker_system_df(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_JSON, "")
        },
    )
    p = DockerProvider(sh)
    entries = p.discover()
    # One entry per non-zero-reclaimable category
    ids = {e.id for e in entries}
    assert "images" in ids
    assert "volumes" in ids
    assert "build-cache" in ids
    # Containers had 0 reclaimable → omitted
    assert "containers" not in ids


def test_entries_have_prune_recipes(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_JSON, "")
        },
    )
    entries = DockerProvider(sh).discover()
    by_id = {e.id: e for e in entries}
    assert by_id["images"].recipe == ["docker image prune -a -f"]
    assert by_id["volumes"].recipe == ["docker volume prune -f"]
    assert by_id["build-cache"].recipe == ["docker builder prune -a -f"]


def test_risk_is_reclaimable(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_JSON, "")
        },
    )
    for e in DockerProvider(sh).discover():
        assert e.risk == Risk.RECLAIMABLE


def test_discover_handles_df_failure(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(1, "", "daemon not running")
        },
    )
    assert DockerProvider(sh).discover() == []


# Modern Docker emits NDJSON — one aggregate object per line, keyed by "Type",
# with "Local Volumes" / "Build Cache" as the volume/cache type names.
_DOCKER_DF_NDJSON = "\n".join(
    [
        '{"Type":"Images","TotalCount":"12","Active":"3","Size":"8GB","Reclaimable":"5GB (62%)"}',
        '{"Type":"Containers","TotalCount":"2","Active":"1","Size":"1GB","Reclaimable":"0B (0%)"}',
        '{"Type":"Local Volumes","TotalCount":"4","Active":"1","Size":"6GB","Reclaimable":"6GB (100%)"}',
        '{"Type":"Build Cache","TotalCount":"30","Active":"0","Size":"3GB","Reclaimable":"3GB"}',
    ]
)


def test_discover_parses_ndjson_output(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_NDJSON, "")
        },
    )
    entries = {e.id: e for e in DockerProvider(sh).discover()}
    assert set(entries) == {"images", "volumes", "build-cache"}  # containers: 0 reclaimable
    assert entries["images"].size_bytes == 5_000_000_000
    assert entries["volumes"].size_bytes == 6_000_000_000
    assert entries["build-cache"].size_bytes == 3_000_000_000
    assert entries["volumes"].recipe == ["docker volume prune -f"]


def test_discover_handles_unparseable_output(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, "not json at all", "")
        },
    )
    assert DockerProvider(sh).discover() == []
