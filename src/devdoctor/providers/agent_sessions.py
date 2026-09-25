"""Agent session stores, offered by age (#84).

Transcripts are the user's history, not a cache. Each provider here turns its
store into *session records* and hands them to :func:`bucket_entries`, which
groups them into fixed age buckets: one entry per bucket, never one per
session. A bucket's age is its newest member, so ``--older-than 90d`` selects
exactly the buckets whose every member is at least 90 days old.

Buckets younger than the retention floor are dangerous and advice only; buckets
at or beyond it are reclaimable, with one delete action per member. Ids are the
bucket alone ("90-180d"); discovery prefixes the provider name. The floor
defaults to 90 days and can be raised or lowered with
``DEVDOCTOR_SESSION_RETENTION_DAYS``, never below 30. Bucket edges never move,
so an entry's id is stable across scans and snapshots line up.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat as stat_mod
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from devdoctor.providers.base import Provider, _stat_kwargs
from devdoctor.sizer import allocated_bytes, size_many
from devdoctor.types import (
    AdviceAction,
    CleanupAction,
    DeletePathAction,
    DiskUsage,
    Entry,
    Risk,
)

RETENTION_ENV = "DEVDOCTOR_SESSION_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 30
SECONDS_PER_DAY = 86_400
_A_YEAR = 365

# (lower, upper) in days; upper None is open-ended. Fixed: ids depend on them.
BUCKETS: tuple[tuple[int, int | None], ...] = (
    (0, 30),
    (30, 90),
    (90, 180),
    (180, 365),
    (365, None),
)


def retention_floor_days() -> int:
    """Days a session must be untouched before it is offered; never under 30."""
    raw = os.environ.get(RETENTION_ENV)
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return max(value, MIN_RETENTION_DAYS)


@dataclass(frozen=True)
class SessionRecord:
    """One session: the paths that are it, when it was last touched, what it occupies."""

    paths: tuple[Path, ...]
    mtime: float
    size_bytes: int


def _bucket_id(lower: int, upper: int | None) -> str:
    return f"{lower}-{upper}d" if upper is not None else f"{lower}d+"


def _bucket_words(lower: int, upper: int | None) -> str:
    if lower == 0:
        return f"under {upper} days"
    if upper is None:
        return "over a year" if lower == _A_YEAR else f"over {lower} days"
    return f"{lower} to {upper} days"


def bucket_entries(
    provider: Provider,
    root: Path,
    records: Iterable[SessionRecord],
    *,
    title: str,
    noun: str = "sessions",
    now: float | None = None,
) -> list[Entry]:
    """One entry per non-empty age bucket, oldest members first within a bucket.

    ``title`` names the tool ("Codex"); ``root`` is the store, shown as the
    entry's path. Members are deleted one action each: files with ``rm -f``,
    directories recursively.
    """
    clock = time.time() if now is None else now
    floor = retention_floor_days()
    grouped: dict[tuple[int, int | None], list[SessionRecord]] = {b: [] for b in BUCKETS}
    for record in records:
        age_days = (clock - record.mtime) / SECONDS_PER_DAY
        for lower, upper in BUCKETS:
            if age_days >= lower and (upper is None or age_days < upper):
                grouped[(lower, upper)].append(record)
                break
        else:
            # Touched in the future: as young as it gets.
            grouped[BUCKETS[0]].append(record)

    entries: list[Entry] = []
    stat_kwargs = _stat_kwargs(root)
    for (lower, upper), members in grouped.items():
        if not members:
            continue
        members.sort(key=lambda r: r.mtime)
        size = sum(r.size_bytes for r in members)
        newest = max(r.mtime for r in members)
        offered = lower >= floor
        actions: tuple[CleanupAction, ...]
        if offered:
            actions = tuple(
                DeletePathAction(path, recursive=path.is_dir())
                for record in members
                for path in record.paths
            )
        else:
            actions = (
                AdviceAction(
                    f"Recent history: DevDoctor never offers {noun} untouched for less than "
                    f"{floor} days. Set {RETENTION_ENV} to change the floor (never below "
                    f"{MIN_RETENTION_DAYS})."
                ),
            )
        count = len(members)
        entries.append(
            Entry(
                provider=provider.name,
                id=_bucket_id(lower, upper),
                path=root,
                label=(
                    f"{title} {noun} untouched {_bucket_words(lower, upper)} · "
                    f"{count} {noun if count != 1 else noun.rstrip('s')}"
                ),
                size_bytes=size,
                mtime=newest,
                risk=Risk.RECLAIMABLE if offered else Risk.DANGEROUS,
                recipe=[],
                usage=DiskUsage(size, size if offered else None),
                actions=actions,
                **stat_kwargs,
            )
        )
    return entries


def _regular_file(path: Path) -> os.stat_result | None:
    """The lstat of a regular file, or None for a symlink, directory or error."""
    try:
        st = path.lstat()
    except OSError:
        return None
    return st if stat_mod.S_ISREG(st.st_mode) else None


def _real_dir(path: Path) -> bool:
    try:
        return stat_mod.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _sqlite_family_bytes(db: Path) -> int:
    """The database plus its -wal and -shm files, as allocated."""
    total = 0
    for candidate in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        st = _regular_file(candidate)
        if st is not None:
            total += allocated_bytes(st)
    return total


def _count_by_bucket(mtimes: Iterable[float], now: float) -> dict[tuple[int, int | None], int]:
    counts = dict.fromkeys(BUCKETS, 0)
    for mtime in mtimes:
        age_days = (now - mtime) / SECONDS_PER_DAY
        for lower, upper in BUCKETS:
            if age_days >= lower and (upper is None or age_days < upper):
                counts[(lower, upper)] += 1
                break
        else:
            counts[BUCKETS[0]] += 1
    return counts


# --- Codex ------------------------------------------------------------------

_CODEX_SESSION = re.compile(r"^rollout-\d{4}-\d{2}-\d{2}T[\d-]+-[0-9a-f-]{36}\.jsonl$")


class CodexSessionsProvider(Provider):
    name = "codex-sessions"
    family = "agent-sessions"
    description = "Codex CLI session transcripts, by age"
    platforms = ("darwin", "linux")
    risk = Risk.DANGEROUS
    details = (
        "Groups ~/.codex/sessions/*/rollout-*.jsonl into age buckets. Buckets untouched "
        "for the retention floor (90 days unless DEVDOCTOR_SESSION_RETENTION_DAYS says "
        "otherwise) are offered one file at a time; younger buckets are shown and never "
        "offered. Codex's own thread index and logs (SQLite) are sized as advice only."
    )

    def discover(self) -> list[Entry]:
        home = Path.home() / ".codex"
        sessions = home / "sessions"
        entries: list[Entry] = []
        if _real_dir(sessions):
            entries.extend(bucket_entries(self, sessions, self._records(sessions), title="Codex"))
        indexes = sorted(
            p
            for p in home.glob("*.sqlite")
            if _regular_file(p) is not None
            and (p.name.startswith("thread_history") or p.name.startswith("logs"))
        )
        if indexes:
            size = sum(_sqlite_family_bytes(p) for p in indexes)
            entries.append(
                Entry(
                    provider=self.name,
                    id="indexes",
                    path=home,
                    label=f"Codex thread index and logs · {len(indexes)} databases",
                    size_bytes=size,
                    mtime=max(p.lstat().st_mtime for p in indexes),
                    risk=Risk.DANGEROUS,
                    recipe=[],
                    usage=DiskUsage(size, None),
                    actions=(
                        AdviceAction(
                            "Codex keeps its thread index and logs in SQLite and prunes "
                            "them itself; DevDoctor never edits a database in place. "
                            "After Codex prunes, VACUUM gives the space back."
                        ),
                    ),
                    **_stat_kwargs(home),
                )
            )
        return entries

    @staticmethod
    def _records(sessions: Path) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for dirpath, _dirnames, filenames in os.walk(sessions, followlinks=False):
            for name in filenames:
                if not _CODEX_SESSION.match(name):
                    continue
                path = Path(dirpath) / name
                st = _regular_file(path)
                if st is None:
                    continue
                records.append(SessionRecord((path,), st.st_mtime, allocated_bytes(st)))
        return records


# --- Claude Code ------------------------------------------------------------

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ClaudeCodeSessionsProvider(Provider):
    name = "claude-code-sessions"
    family = "agent-sessions"
    description = "Claude Code session transcripts, by age"
    platforms = ("darwin", "linux")
    risk = Risk.DANGEROUS
    details = (
        "A session is ~/.claude/projects/<project>/<uuid>.jsonl plus the <uuid>/ directory "
        "beside it (subagent transcripts, tool results); its age is the newest of the two. "
        "Sessions are grouped into age buckets and offered only past the retention floor "
        "(90 days unless DEVDOCTOR_SESSION_RETENTION_DAYS says otherwise). The memory/ "
        "directory and anything else in a project folder are never part of a session."
    )

    def discover(self) -> list[Entry]:
        projects = Path.home() / ".claude" / "projects"
        if not _real_dir(projects):
            return []
        return bucket_entries(self, projects, self._records(projects), title="Claude Code")

    def _records(self, projects: Path) -> list[SessionRecord]:
        files: list[tuple[Path, os.stat_result, Path | None]] = []
        for project in sorted(projects.iterdir()):
            if not _real_dir(project):
                continue
            for transcript in sorted(project.glob("*.jsonl")):
                if not _UUID.match(transcript.stem):
                    continue
                st = _regular_file(transcript)
                if st is None:
                    continue
                sibling = transcript.with_suffix("")
                files.append((transcript, st, sibling if _real_dir(sibling) else None))
        dirs = [sibling for _t, _st, sibling in files if sibling is not None]
        sizings = dict(zip(dirs, size_many(dirs), strict=True))
        records: list[SessionRecord] = []
        for transcript, st, directory in files:
            paths: tuple[Path, ...] = (transcript,)
            mtime, size = st.st_mtime, allocated_bytes(st)
            if directory is not None:
                sizing = sizings[directory]
                self._note_skipped(list(sizing.skipped_paths))
                paths = (transcript, directory)
                size += sizing.allocated_bytes
                if sizing.newest_mtime is not None:
                    mtime = max(mtime, sizing.newest_mtime)
            records.append(SessionRecord(paths, mtime, size))
        return records


# --- OpenCode ---------------------------------------------------------------


def _opencode_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(os.path.expanduser(xdg)) if xdg else Path.home() / ".local" / "share"
    return base / "opencode"


class OpenCodeSessionsProvider(Provider):
    name = "opencode-sessions"
    family = "agent-sessions"
    description = "OpenCode's session database, with sessions counted by age"
    platforms = ("darwin", "linux")
    risk = Risk.DANGEROUS
    details = (
        "OpenCode keeps every session in one SQLite database. DevDoctor reads it read-only "
        "to count sessions by age and never edits it: delete old sessions in the app, then "
        "VACUUM gives the space back."
    )

    def discover(self) -> list[Entry]:
        db = _opencode_data_dir() / "opencode.db"
        st = _regular_file(db)
        if st is None:
            return []
        size = _sqlite_family_bytes(db)
        advice = self._advice(db)
        return [
            Entry(
                provider=self.name,
                id="database",
                path=db,
                label="OpenCode session database",
                size_bytes=size,
                mtime=st.st_mtime,
                risk=Risk.DANGEROUS,
                recipe=[],
                usage=DiskUsage(size, None),
                actions=(AdviceAction(advice),),
                **_stat_kwargs(db),
            )
        ]

    def _advice(self, db: Path) -> str:
        tail = (
            "OpenCode has no retention setting: delete old sessions in the app, then run "
            "VACUUM on the database to give the space back. DevDoctor never edits it."
        )
        mtimes = self._session_mtimes(db)
        if mtimes is None:
            return tail
        counts = _count_by_bucket(mtimes, time.time())
        floor = retention_floor_days()
        old = sum(n for (lower, _upper), n in counts.items() if lower >= floor)
        return f"{len(mtimes)} sessions, {old} untouched for {floor} days or more. {tail}"

    def _session_mtimes(self, db: Path) -> list[float] | None:
        """Epoch seconds of each session's last update, read-only; None when unreadable."""
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0) as conn:
                rows = conn.execute("SELECT time_updated FROM session").fetchall()
        except sqlite3.Error as exc:
            self.diagnostics.append(
                f"{self.name}: could not read the session table ({exc}); sizes only"
            )
            return None
        mtimes: list[float] = []
        for (value,) in rows:
            if isinstance(value, (int, float)):
                # Stored in milliseconds; a value that small must be seconds.
                mtimes.append(float(value) / 1000 if value > 10**11 else float(value))
        return mtimes


__all__ = [
    "BUCKETS",
    "ClaudeCodeSessionsProvider",
    "CodexSessionsProvider",
    "OpenCodeSessionsProvider",
    "SessionRecord",
    "bucket_entries",
    "retention_floor_days",
]
