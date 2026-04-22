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
SNAPSHOT_SCHEMA_VERSION = 1


class Risk(StrEnum):
    SAFE = "safe"
    RECLAIMABLE = "reclaimable"
    DANGEROUS = "dangerous"


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
            }

        payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "entries": [serialize_entry(e) for e in self.entries],
            "scanned_at": self.scanned_at.isoformat(),
            "hostname": self.hostname,
            "platform": self.platform,
            "note": self.note,
            "skipped_paths": list(self.skipped_paths),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, data: str) -> Report:
        payload = json.loads(data)
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
            )
            for e in payload["entries"]
        ]
        return cls(
            entries=entries,
            scanned_at=datetime.fromisoformat(payload["scanned_at"]),
            hostname=payload["hostname"],
            platform=payload["platform"],
            note=payload.get("note"),
            skipped_paths=list(payload.get("skipped_paths", [])),
        )


# Choice letters: y=yes, n=no, a=all-remaining-in-provider, s=skip-provider, q=quit
Choice = Literal["y", "n", "a", "s", "q"]
PromptChoice = Callable[[Entry], Choice]
Confirm = Callable[[str], bool]

AsyncPromptChoice = Callable[[Entry], Awaitable[Choice]]
AsyncConfirm = Callable[[str], Awaitable[bool]]
AsyncRunLine = Callable[[str], Awaitable[ShellResult]]
