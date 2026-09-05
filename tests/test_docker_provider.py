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

_VOLUME_DETAILS_COMMAND = (
    "docker",
    "system",
    "df",
    "--verbose",
    "--format",
    "{{json .Volumes}}",
)

_VOLUME_DETAILS = json.dumps(
    [
        {
            "Name": "anon-cache",
            "Links": "0",
            "Size": "1GB",
            "Labels": "com.docker.volume.anonymous=",
        },
        {
            "Name": "pgdata",
            "Links": "0",
            "Size": "4GB",
            "Labels": "com.docker.compose.project=app,com.docker.compose.volume=db",
        },
        {
            "Name": "active-data",
            "Links": "1",
            "Size": "2GB",
            "Labels": "",
        },
    ]
)


def _shell_with_df(df_output: str, volume_details: str = _VOLUME_DETAILS) -> FakeShell:
    return FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, df_output, ""),
            _VOLUME_DETAILS_COMMAND: ShellResult(0, volume_details, ""),
        },
    )


def test_discover_parses_docker_system_df(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = _shell_with_df(_DOCKER_DF_JSON)
    p = DockerProvider(sh)
    entries = p.discover()
    # One entry per non-zero-reclaimable category
    ids = {e.id for e in entries}
    assert "images" in ids
    assert "volume:anon-cache" in ids
    assert "volume:pgdata" in ids
    assert "build-cache" in ids
    assert "volume:active-data" not in ids
    # Containers had 0 reclaimable → omitted
    assert "containers" not in ids


def test_entries_have_prune_recipes(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = _shell_with_df(_DOCKER_DF_JSON)
    entries = DockerProvider(sh).discover()
    by_id = {e.id: e for e in entries}
    assert by_id["images"].recipe == ["docker image prune -a -f"]
    assert by_id["volume:anon-cache"].recipe == ["docker volume rm anon-cache"]
    assert by_id["volume:pgdata"].recipe == ["docker volume rm pgdata"]
    assert by_id["build-cache"].recipe == ["docker builder prune -a -f"]


def test_named_volumes_are_dangerous_and_anonymous_volumes_are_reclaimable(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    entries = {e.id: e for e in DockerProvider(_shell_with_df(_DOCKER_DF_JSON)).discover()}
    assert entries["images"].risk == Risk.RECLAIMABLE
    assert entries["volume:anon-cache"].risk == Risk.RECLAIMABLE
    assert entries["volume:pgdata"].risk == Risk.DANGEROUS


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
    volume_details = json.dumps(
        [
            {
                "Name": "anon-cache",
                "Links": 0,
                "Size": "1GB",
                "Labels": {"com.docker.volume.anonymous": ""},
            },
            {"Name": "pgdata", "Links": 0, "Size": "5GB", "Labels": {}},
        ]
    )
    sh = _shell_with_df(_DOCKER_DF_NDJSON, volume_details)
    entries = {e.id: e for e in DockerProvider(sh).discover()}
    assert set(entries) == {
        "images",
        "volume:anon-cache",
        "volume:pgdata",
        "build-cache",
    }  # containers: 0 reclaimable
    assert entries["images"].size_bytes == 5_000_000_000
    assert entries["volume:anon-cache"].size_bytes == 1_000_000_000
    assert entries["volume:pgdata"].size_bytes == 5_000_000_000
    assert entries["build-cache"].size_bytes == 3_000_000_000
    assert entries["volume:pgdata"].recipe == ["docker volume rm pgdata"]


def test_volume_details_support_lowercase_kb_and_skip_referenced_volumes(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    details = json.dumps(
        [
            {
                "Name": "tiny-anon",
                "Links": "0",
                "Size": "12.5kB",
                "Labels": ["com.docker.volume.anonymous="],
            },
            {"Name": "still-used", "Links": "2", "Size": "5GB", "Labels": ""},
        ]
    )
    summary = '{"Type":"Local Volumes","Reclaimable":"12.5kB (100%)"}'
    entries = DockerProvider(_shell_with_df(summary, details)).discover()
    assert [(e.id, e.size_bytes) for e in entries] == [("volume:tiny-anon", 12_500)]


def test_empty_unused_volumes_are_ignored_without_a_parse_warning(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    details = json.dumps(
        [
            {
                "Name": "empty-anon",
                "Links": "0",
                "Size": "0B",
                "Labels": "com.docker.volume.anonymous=",
            },
            {
                "Name": "populated-anon",
                "Links": "0",
                "Size": "1MB",
                "Labels": "com.docker.volume.anonymous=",
            },
        ]
    )
    summary = '{"Type":"Local Volumes","Reclaimable":"1MB (100%)"}'
    provider = DockerProvider(_shell_with_df(summary, details))

    entries = provider.discover()

    assert [entry.id for entry in entries] == ["volume:populated-anon"]
    assert provider.diagnostics == []


def test_volume_cleanup_is_disabled_when_details_fail(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_NDJSON, ""),
            _VOLUME_DETAILS_COMMAND: ShellResult(1, "", "unsupported format"),
        },
    )
    provider = DockerProvider(sh)
    entries = provider.discover()
    assert all(not entry.id.startswith("volume:") for entry in entries)
    assert any("volume cleanup was disabled" in note for note in provider.diagnostics)


def test_discover_handles_unparseable_output(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, "not json at all", "")
        },
    )
    assert DockerProvider(sh).discover() == []
