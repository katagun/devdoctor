"""Agent session stores are offered by age, never wholesale (#84)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import click.testing
from click.testing import CliRunner

from devdoctor.cli import build_cli
from devdoctor.providers.agent_sessions import (
    BUCKETS,
    ClaudeCodeSessionsProvider,
    CodexSessionsProvider,
    OpenCodeSessionsProvider,
    SessionRecord,
    bucket_entries,
    retention_floor_days,
)
from devdoctor.registry import load_providers
from devdoctor.types import AdviceAction, DeletePathAction, Risk, ShellResult
from tests.conftest import FakeShell

DAY = 86_400
NOW = 1_800_000_000.0


def _aged(path: Path, days: float, size: int = 4096, *, now: float = NOW) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (now - days * DAY, now - days * DAY))
    return path


def _codex_session(sessions: Path, days: float, tag: str = "0", **kw) -> Path:
    name = f"rollout-2026-01-12T12-40-16-019bb3b9-2e76-7ab3-960d-2c8734c9{tag:0>4}.jsonl"
    return _aged(sessions / "2026" / "01" / "12" / name, days, **kw)


# --- the shared helper ---------------------------------------------------------


def test_retention_floor_defaults_and_never_drops_below_thirty(monkeypatch) -> None:
    monkeypatch.delenv("DEVDOCTOR_SESSION_RETENTION_DAYS", raising=False)
    assert retention_floor_days() == 90
    monkeypatch.setenv("DEVDOCTOR_SESSION_RETENTION_DAYS", "120")
    assert retention_floor_days() == 120
    monkeypatch.setenv("DEVDOCTOR_SESSION_RETENTION_DAYS", "7")
    assert retention_floor_days() == 30
    monkeypatch.setenv("DEVDOCTOR_SESSION_RETENTION_DAYS", "soon")
    assert retention_floor_days() == 90


def test_buckets_have_fixed_edges_and_stable_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEVDOCTOR_SESSION_RETENTION_DAYS", raising=False)
    provider = CodexSessionsProvider(FakeShell())
    root = tmp_path / "store"
    root.mkdir()
    records = [
        SessionRecord((root / "a",), NOW - 89.5 * DAY, 10),
        SessionRecord((root / "b",), NOW - 90.5 * DAY, 20),
        SessionRecord((root / "c",), NOW - 100 * DAY, 30),
        SessionRecord((root / "d",), NOW - 400 * DAY, 40),
    ]

    entries = bucket_entries(provider, root, records, title="Codex", now=NOW)

    # Discovery prefixes ids with the provider name; the raw id is the bucket.
    assert [e.id for e in entries] == ["30-90d", "90-180d", "365d+"]
    young, old, ancient = entries
    # Younger than the floor: shown, sized, never offered.
    assert young.risk is Risk.DANGEROUS
    assert isinstance(young.actions[0], AdviceAction)
    assert young.reclaimable_bytes is None
    assert young.label == "Codex sessions untouched 30 to 90 days · 1 session"
    # At the floor: one delete per member, the bucket is as young as its newest member.
    assert old.risk is Risk.RECLAIMABLE
    assert old.actions == (
        DeletePathAction(root / "c", recursive=False),
        DeletePathAction(root / "b", recursive=False),
    )
    assert old.size_bytes == 50 and old.reclaimable_bytes == 50
    assert old.mtime == NOW - 90.5 * DAY
    assert old.label == "Codex sessions untouched 90 to 180 days · 2 sessions"
    assert ancient.label == "Codex sessions untouched over a year · 1 session"
    assert all(e.path == root for e in entries)
    assert len(BUCKETS) == 5


def test_a_higher_floor_moves_the_risk_boundary_not_the_edges(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEVDOCTOR_SESSION_RETENTION_DAYS", "180")
    provider = CodexSessionsProvider(FakeShell())
    root = tmp_path / "store"
    root.mkdir()
    records = [
        SessionRecord((root / "b",), NOW - 100 * DAY, 20),
        SessionRecord((root / "d",), NOW - 200 * DAY, 40),
    ]

    entries = bucket_entries(provider, root, records, title="Codex", now=NOW)

    assert [(e.id, e.risk) for e in entries] == [
        ("90-180d", Risk.DANGEROUS),
        ("180-365d", Risk.RECLAIMABLE),
    ]
    assert "180 days" in entries[0].actions[0].message  # type: ignore[union-attr]


# --- Codex --------------------------------------------------------------------


def test_codex_sessions_are_bucketed_and_only_transcripts_count(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DEVDOCTOR_SESSION_RETENTION_DAYS", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    sessions = home / ".codex" / "sessions"
    fresh = _codex_session(sessions, 3, "1", now=time.time())
    stale = _codex_session(sessions, 120, "2", now=time.time())
    _aged(sessions / "2026" / "01" / "12" / "notes.txt", 400, now=time.time())
    (sessions / "2026" / "link.jsonl").symlink_to(stale)
    _aged(home / ".codex" / "thread_history_1.sqlite", 1, 8192, now=time.time())
    _aged(home / ".codex" / "thread_history_1.sqlite-wal", 1, 4096, now=time.time())
    _aged(home / ".codex" / "logs_2.sqlite", 1, 4096, now=time.time())

    entries = {e.id: e for e in CodexSessionsProvider(FakeShell()).discover()}

    assert set(entries) == {"0-30d", "90-180d", "indexes"}
    assert entries["90-180d"].actions == (DeletePathAction(stale, recursive=False),)
    assert isinstance(entries["0-30d"].actions[0], AdviceAction)
    assert entries["0-30d"].size_bytes == fresh.lstat().st_blocks * 512
    indexes = entries["indexes"]
    assert indexes.risk is Risk.DANGEROUS
    assert indexes.size_bytes == 8192 + 4096 + 4096
    assert "VACUUM" in indexes.actions[0].message  # type: ignore[union-attr]


def test_codex_without_a_store_is_silent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert CodexSessionsProvider(FakeShell()).discover() == []


# --- Claude Code --------------------------------------------------------------


def test_claude_code_session_is_transcript_plus_sibling_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DEVDOCTOR_SESSION_RETENTION_DAYS", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    project = home / ".claude" / "projects" / "-Users-x-proj"
    uuid = "d58c4abc-456f-4c70-a919-55b579f0a8d6"
    now = time.time()
    transcript = _aged(project / f"{uuid}.jsonl", 200, 4096, now=now)
    # A tool result written later than the transcript makes the session that recent.
    result = _aged(project / uuid / "tool-results" / "r1.txt", 100, 4096, now=now)
    for directory in (project / uuid / "tool-results", project / uuid):
        os.utime(directory, (now - 100 * DAY, now - 100 * DAY))
    memory = _aged(project / "memory" / "MEMORY.md", 500, 4096, now=now)
    _aged(project / "custom-title.json", 500, now=now)
    _aged(project / "not-a-uuid.jsonl", 500, now=now)
    (home / ".claude" / "projects" / "linked").symlink_to(project)

    entries = ClaudeCodeSessionsProvider(FakeShell()).discover()

    (entry,) = entries
    assert entry.id == "90-180d"
    assert entry.actions == (
        DeletePathAction(transcript, recursive=False),
        DeletePathAction(project / uuid, recursive=True),
    )
    assert entry.size_bytes == transcript.lstat().st_blocks * 512 + result.lstat().st_blocks * 512
    assert entry.label == "Claude Code sessions untouched 90 to 180 days · 1 session"
    assert memory.exists()
    assert not any(memory in a.path.parents or a.path == memory for a in entry.actions)  # type: ignore[union-attr]


# --- OpenCode -----------------------------------------------------------------


def _opencode_db(home: Path, updated_days: list[float]) -> Path:
    db = home / ".local" / "share" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE session (id TEXT PRIMARY KEY, time_updated INTEGER NOT NULL)")
        now_ms = int(time.time() * 1000)
        conn.executemany(
            "INSERT INTO session VALUES (?, ?)",
            [(f"s{i}", now_ms - int(d * DAY * 1000)) for i, d in enumerate(updated_days)],
        )
    return db


def test_opencode_counts_sessions_read_only_and_never_offers_the_database(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DEVDOCTOR_SESSION_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    db = _opencode_db(home, [2, 95, 400])
    before = db.read_bytes()

    provider = OpenCodeSessionsProvider(FakeShell())
    (entry,) = provider.discover()

    assert entry.risk is Risk.DANGEROUS
    assert entry.reclaimable_bytes is None
    assert entry.path == db
    message = entry.actions[0].message  # type: ignore[union-attr]
    assert message.startswith("3 sessions, 2 untouched for 90 days or more.")
    assert "VACUUM" in message
    assert provider.diagnostics == []
    assert db.read_bytes() == before


def test_opencode_unreadable_database_is_still_sized(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    db = home / ".local" / "share" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"not a database" * 100)

    provider = OpenCodeSessionsProvider(FakeShell())
    (entry,) = provider.discover()

    assert entry.size_bytes > 0
    assert "OpenCode has no retention setting" in entry.actions[0].message  # type: ignore[union-attr]
    assert any("could not read the session table" in note for note in provider.diagnostics)


# --- registry and the cleanup path ---------------------------------------------


def test_registry_has_the_agent_sessions_family() -> None:
    families = {p.name: p.family for p in load_providers(FakeShell())}
    assert {
        families["codex-sessions"],
        families["claude-code-sessions"],
        families["opencode-sessions"],
    } == {"agent-sessions"}


def test_clean_older_than_removes_old_transcripts_one_by_one(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEVDOCTOR_SESSION_RETENTION_DAYS", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    sessions = home / ".codex" / "sessions"
    now = time.time()
    fresh = _codex_session(sessions, 3, "1", now=now)
    old_a = _codex_session(sessions, 120, "2", now=now)
    old_b = _codex_session(sessions, 130, "3", now=now)
    monkeypatch.setattr(click.testing._NamedTextIOWrapper, "isatty", lambda self: True)
    shell = FakeShell(
        which_table={"ollama": None, "docker": None},
        responses={
            ("rm", "-f", "--", str(old_a)): ShellResult(0, "", ""),
            ("rm", "-f", "--", str(old_b)): ShellResult(0, "", ""),
        },
    )

    result = CliRunner().invoke(
        build_cli(shell),
        ["clean", "--execute", "--yes", "--provider", "codex-sessions", "--older-than", "90d"],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert sorted(shell.calls) == sorted(
        [("rm", "-f", "--", str(old_b)), ("rm", "-f", "--", str(old_a))]
    )
    assert str(fresh) not in result.output.replace("\n", "")
    assert "(+1 more)" in result.output


def test_allow_dangerous_still_executes_nothing_for_a_young_bucket(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DEVDOCTOR_SESSION_RETENTION_DAYS", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _codex_session(home / ".codex" / "sessions", 3, "1", now=time.time())
    monkeypatch.setattr(click.testing._NamedTextIOWrapper, "isatty", lambda self: True)
    shell = FakeShell(which_table={"ollama": None, "docker": None})

    result = CliRunner().invoke(
        build_cli(shell),
        ["clean", "--execute", "--yes", "--allow-dangerous", "--provider", "codex-sessions"],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert shell.calls == []
    assert "skipped" in result.output
