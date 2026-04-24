from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

# Schema version written into every snapshot. Bump when a non-additive change
# to the Report format would confuse old readers (e.g. renaming/removing a
# field). Purely additive changes don't need a bump — unknown keys are ignored
# on read.
SNAPSHOT_SCHEMA_VERSION = 2


class Risk(StrEnum):
    SAFE = "safe"
    RECLAIMABLE = "reclaimable"
    DANGEROUS = "dangerous"


class SnapshotKind(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


@dataclass(frozen=True)
class ProviderTiming:
    name: str
    bytes: int
    entries: int
    duration_ms: int


@dataclass(frozen=True)
class Entry:
    provider: str
    id: str
    path: Path | None
    label: str
    size_bytes: int
    mtime: float | None
    risk: Risk
    recipe: list[str]
    # Stat-derived fields. Populated when the entry is backed by a real
    # filesystem path; None for class-based providers whose entries are
    # logical identifiers (ollama models, docker images).
    uid: int | None = None
    gid: int | None = None
    mode: int | None = None
    owner: str | None = None  # login name, resolved via pwd.getpwuid
    group: str | None = None  # group name, resolved via grp.getgrgid
    perms: str | None = None  # stat.filemode string, e.g. "drwxr-xr-x"


@dataclass(frozen=True)
class ShellResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ScanFilters:
    min_size_bytes: int = 0
    risks: frozenset[Risk] | None = None
    providers: frozenset[str] | None = None


@dataclass(frozen=True)
class CleanupOpts:
    execute: bool = False
    yes_safe: bool = False
    allow_dangerous: bool = False
    providers: frozenset[str] | None = None


@dataclass
class CleanResult:
    entry_id: str
    status: Literal["ok", "skipped", "error", "dry_run"]
    freed_bytes: int
    message: str | None = None


@dataclass(frozen=True)
class DiffRow:
    provider: str
    before_bytes: int
    after_bytes: int
    delta_bytes: int
    delta_pct: float


@dataclass
class DiffReport:
    before_at: datetime
    after_at: datetime
    rows: list[DiffRow]


@dataclass
class Report:
    entries: list[Entry]
    scanned_at: datetime
    hostname: str
    platform: str
    note: str | None = None
    skipped_paths: list[str] = field(default_factory=list)
    # Telemetry — defaults preserve the pre-v2 semantics so ad-hoc callers
    # (tests, CLI) that construct Report by hand keep working unchanged.
    kind: SnapshotKind = SnapshotKind.MANUAL
    started_at: datetime | None = None
    duration_ms: int | None = None
    per_provider: list[ProviderTiming] = field(default_factory=list)

    def total_bytes(self) -> int:
        return sum(e.size_bytes for e in self.entries)

    def by_provider(self) -> dict[str, list[Entry]]:
        out: dict[str, list[Entry]] = {}
        for e in self.entries:
            out.setdefault(e.provider, []).append(e)
        return out

    def filter(
        self,
        *,
        risks: set[Risk] | frozenset[Risk] | None = None,
        min_size: int = 0,
        providers: set[str] | frozenset[str] | None = None,
    ) -> Report:
        def keep(e: Entry) -> bool:
            if risks is not None and e.risk not in risks:
                return False
            if providers is not None and e.provider not in providers:
                return False
            return e.size_bytes >= min_size

        return Report(
            entries=[e for e in self.entries if keep(e)],
            scanned_at=self.scanned_at,
            hostname=self.hostname,
            platform=self.platform,
            note=self.note,
            skipped_paths=list(self.skipped_paths),
            kind=self.kind,
            started_at=self.started_at,
            duration_ms=self.duration_ms,
            per_provider=list(self.per_provider),
        )

    def to_json(self) -> str:
        def serialize_entry(e: Entry) -> dict[str, object]:
            return {
                "provider": e.provider,
                "id": e.id,
                "path": str(e.path) if e.path is not None else None,
                "label": e.label,
                "size_bytes": e.size_bytes,
                "mtime": e.mtime,
                "risk": e.risk.value,
                "recipe": list(e.recipe),
                "uid": e.uid,
                "gid": e.gid,
                "mode": e.mode,
                "owner": e.owner,
                "group": e.group,
                "perms": e.perms,
            }

        entries_payload: list[dict[str, object]] | None
        if self.kind == SnapshotKind.AUTO:
            entries_payload = None
        else:
            entries_payload = [serialize_entry(e) for e in self.entries]

        per_provider_payload = [
            {
                "name": pt.name,
                "bytes": pt.bytes,
                "entries": pt.entries,
                "duration_ms": pt.duration_ms,
            }
            for pt in self.per_provider
        ]

        payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "kind": self.kind.value,
            "scanned_at": self.scanned_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at is not None else None,
            "duration_ms": self.duration_ms,
            "hostname": self.hostname,
            "platform": self.platform,
            "note": self.note,
            "total_bytes": self.total_bytes(),
            "entry_count": len(self.entries),
            "per_provider": per_provider_payload,
            "entries": entries_payload,
            "skipped_paths": list(self.skipped_paths),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, data: str) -> Report:
        payload = json.loads(data)
        # `entries` may be `null` for auto-snapshots. Callers expecting a list
        # get an empty list — iterating an auto-snapshot's entries is legal
        # but yields nothing.
        raw_entries = payload.get("entries") or []
        entries = [
            Entry(
                provider=e["provider"],
                id=e["id"],
                path=Path(e["path"]) if e["path"] is not None else None,
                label=e["label"],
                size_bytes=e["size_bytes"],
                mtime=e["mtime"],
                risk=Risk(e["risk"]),
                recipe=list(e["recipe"]),
                uid=e.get("uid"),
                gid=e.get("gid"),
                mode=e.get("mode"),
                owner=e.get("owner"),
                group=e.get("group"),
                perms=e.get("perms"),
            )
            for e in raw_entries
        ]
        kind_raw = payload.get("kind", "manual")
        kind = SnapshotKind(kind_raw) if kind_raw in {"auto", "manual"} else SnapshotKind.MANUAL

        started_raw = payload.get("started_at")
        started_at = datetime.fromisoformat(started_raw) if started_raw else None

        per_provider_raw = payload.get("per_provider") or []
        per_provider = [
            ProviderTiming(
                name=pt["name"],
                bytes=pt["bytes"],
                entries=pt["entries"],
                duration_ms=pt["duration_ms"],
            )
            for pt in per_provider_raw
        ]

        return cls(
            entries=entries,
            scanned_at=datetime.fromisoformat(payload["scanned_at"]),
            hostname=payload["hostname"],
            platform=payload["platform"],
            note=payload.get("note"),
            skipped_paths=list(payload.get("skipped_paths", [])),
            kind=kind,
            started_at=started_at,
            duration_ms=payload.get("duration_ms"),
            per_provider=per_provider,
        )


# Choice letters: y=yes, n=no, a=all-remaining-in-provider, s=skip-provider, q=quit
Choice = Literal["y", "n", "a", "s", "q"]
PromptChoice = Callable[[Entry], Choice]
Confirm = Callable[[str], bool]

AsyncPromptChoice = Callable[[Entry], Awaitable[Choice]]
AsyncConfirm = Callable[[str], Awaitable[bool]]
AsyncRunLine = Callable[[str], Awaitable[ShellResult]]
