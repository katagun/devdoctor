from __future__ import annotations

import json
import shlex
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
class DiskUsage:
    """Explicit byte semantics for one disk entry.

    None means the provider cannot measure that value. shared_bytes is the
    portion of the footprint also referenced outside the entry and is
    therefore not independently reclaimable.
    """

    footprint_bytes: int | None
    reclaimable_bytes: int | None
    shared_bytes: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("footprint_bytes", self.footprint_bytes),
            ("reclaimable_bytes", self.reclaimable_bytes),
            ("shared_bytes", self.shared_bytes),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class DeletePathAction:
    path: Path
    recursive: bool = True


@dataclass(frozen=True)
class CommandAction:
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.argv or not self.argv[0]:
            raise ValueError("command action argv must not be empty")


@dataclass(frozen=True)
class AdviceAction:
    message: str


CleanupAction = DeletePathAction | CommandAction | AdviceAction


@dataclass(frozen=True)
class HardlinkRecord:
    device: int
    inode: int
    allocated_bytes: int
    link_count: int
    paths: tuple[str, ...]

    @property
    def key(self) -> tuple[int, int]:
        return self.device, self.inode


def render_cleanup_action(action: CleanupAction) -> str:
    if isinstance(action, DeletePathAction):
        flag = "-rf" if action.recursive else "-f"
        return shlex.join(("rm", flag, "--", str(action.path)))
    if isinstance(action, CommandAction):
        return shlex.join(action.argv)
    return f"echo {shlex.quote(action.message)}"


def cleanup_action_argv(action: CleanupAction) -> tuple[str, ...] | None:
    if isinstance(action, DeletePathAction):
        flag = "-rf" if action.recursive else "-f"
        return ("rm", flag, "--", str(action.path))
    if isinstance(action, CommandAction):
        return action.argv
    return None


def cleanup_action_to_dict(action: CleanupAction) -> dict[str, object]:
    if isinstance(action, DeletePathAction):
        return {
            "kind": "delete_path",
            "path": str(action.path),
            "recursive": action.recursive,
        }
    if isinstance(action, CommandAction):
        return {"kind": "command", "argv": list(action.argv)}
    return {"kind": "advice", "message": action.message}


def cleanup_action_from_dict(payload: object) -> CleanupAction | None:
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    if kind == "delete_path" and isinstance(payload.get("path"), str):
        return DeletePathAction(
            path=Path(payload["path"]),
            recursive=bool(payload.get("recursive", True)),
        )
    if kind == "command":
        argv = payload.get("argv")
        if isinstance(argv, list) and argv and all(isinstance(arg, str) for arg in argv):
            return CommandAction(tuple(argv))
    if kind == "advice" and isinstance(payload.get("message"), str):
        return AdviceAction(payload["message"])
    return None


def legacy_recipe_actions(lines: list[str]) -> tuple[CleanupAction, ...]:
    """Convert trusted legacy snapshot/provider recipes to typed argv actions."""
    actions: list[CleanupAction] = []
    for line in lines:
        try:
            argv = tuple(shlex.split(line))
        except ValueError:
            continue
        if argv:
            actions.append(CommandAction(argv))
    return tuple(actions)


@dataclass(frozen=True)
class ProviderTiming:
    name: str
    bytes: int
    entries: int
    duration_ms: int
    footprint_bytes: int | None = None
    reclaimable_bytes: int | None = None
    shared_bytes: int = 0


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
    usage: DiskUsage | None = None
    actions: tuple[CleanupAction, ...] = ()
    hardlinks: tuple[HardlinkRecord, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    # Stat-derived fields. Populated when the entry is backed by a real
    # filesystem path; None for class-based providers whose entries are
    # logical identifiers (ollama models, docker images).
    uid: int | None = None
    gid: int | None = None
    mode: int | None = None
    owner: str | None = None  # login name, resolved via pwd.getpwuid
    group: str | None = None  # group name, resolved via grp.getgrgid
    perms: str | None = None  # stat.filemode string, e.g. "drwxr-xr-x"

    @property
    def footprint_bytes(self) -> int | None:
        return self.usage.footprint_bytes if self.usage is not None else self.size_bytes

    @property
    def reclaimable_bytes(self) -> int | None:
        return self.usage.reclaimable_bytes if self.usage is not None else self.size_bytes

    @property
    def shared_bytes(self) -> int:
        return self.usage.shared_bytes if self.usage is not None else 0

    @property
    def display_bytes(self) -> int:
        return self.footprint_bytes or self.reclaimable_bytes or 0

    def cleanup_actions(self) -> tuple[CleanupAction, ...]:
        return self.actions or legacy_recipe_actions(self.recipe)

    def recipe_lines(self) -> list[str]:
        if self.actions:
            return [render_cleanup_action(action) for action in self.actions]
        return list(self.recipe)


def unique_footprint_bytes(entries: list[Entry]) -> int:
    total = sum(entry.footprint_bytes or 0 for entry in entries)
    seen: set[tuple[int, int]] = set()
    for entry in entries:
        entry_seen: set[tuple[int, int]] = set()
        for record in entry.hardlinks:
            if record.key in entry_seen:
                continue
            entry_seen.add(record.key)
            if record.key in seen:
                total -= record.allocated_bytes
            else:
                seen.add(record.key)
    return max(0, total)


def unique_shared_bytes(entries: list[Entry]) -> int:
    """Return shared allocations once, even when several entries reference them."""
    total = sum(entry.shared_bytes for entry in entries)
    partial_counts: dict[tuple[int, int], tuple[int, int]] = {}
    for entry in entries:
        entry_seen: set[tuple[int, int]] = set()
        for record in entry.hardlinks:
            if record.key in entry_seen or len(set(record.paths)) >= record.link_count:
                continue
            entry_seen.add(record.key)
            allocated, count = partial_counts.get(record.key, (record.allocated_bytes, 0))
            partial_counts[record.key] = allocated, count + 1
    for allocated, count in partial_counts.values():
        total -= max(0, count - 1) * allocated
    return max(0, total)


@dataclass
class _ReclaimableHardlink:
    allocated_bytes: int
    link_count: int
    paths: set[str] = field(default_factory=set)
    full_entries: int = 0


def estimated_reclaimable_bytes(entries: list[Entry]) -> int:
    """Estimate bytes freed by cleaning all ``entries`` together.

    Entry-level reclaimable values exclude hard-linked allocations with links
    outside that entry. A cleanup plan can nevertheless reclaim the allocation
    when its selected entries collectively remove every link. Conversely,
    overlapping entries that each contain every link must count it only once.
    """
    total = sum(entry.reclaimable_bytes or 0 for entry in entries)
    by_inode: dict[tuple[int, int], _ReclaimableHardlink] = {}

    for entry in entries:
        if entry.reclaimable_bytes is None:
            continue
        entry_seen: set[tuple[int, int]] = set()
        for record in entry.hardlinks:
            if record.key in entry_seen:
                continue
            entry_seen.add(record.key)
            item = by_inode.setdefault(
                record.key,
                _ReclaimableHardlink(record.allocated_bytes, record.link_count),
            )
            item.paths.update(record.paths)
            item.link_count = max(item.link_count, record.link_count)
            if len(set(record.paths)) >= record.link_count:
                item.full_entries += 1

    for item in by_inode.values():
        should_count = int(len(item.paths) >= item.link_count)
        total += (should_count - item.full_entries) * item.allocated_bytes

    return max(0, total)


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
    bytes_verified: bool = False


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
    # Human-readable notes about anything that went wrong during the scan but
    # did not abort it — e.g. "N path(s) skipped (permission denied)" from the
    # sizer, or a provider whose discovery command failed. Purely additive and
    # capped by producers; old snapshots without the key default to []. Surfaced
    # in the CLI table and the /api/scan JSON so failures aren't silent.
    diagnostics: list[str] = field(default_factory=list)
    # Telemetry — defaults preserve the pre-v2 semantics so ad-hoc callers
    # (tests, CLI) that construct Report by hand keep working unchanged.
    kind: SnapshotKind = SnapshotKind.MANUAL
    started_at: datetime | None = None
    duration_ms: int | None = None
    per_provider: list[ProviderTiming] = field(default_factory=list)
    # Override for total_bytes(). Populated by from_json() so auto snapshots —
    # whose entries list is intentionally dropped on disk — still report the
    # correct total. Leave None for in-memory Reports; total_bytes() falls back
    # to summing entries.
    _total_bytes_override: int | None = None
    _total_footprint_bytes_override: int | None = None
    _total_reclaimable_bytes_override: int | None = None
    _total_shared_bytes_override: int | None = None
    _unknown_reclaimable_entries_override: int | None = None

    def total_bytes(self) -> int:
        if self._total_bytes_override is not None:
            return self._total_bytes_override
        return sum(e.size_bytes for e in self.entries)

    def total_footprint_bytes(self) -> int:
        if self._total_footprint_bytes_override is not None:
            return self._total_footprint_bytes_override
        return unique_footprint_bytes(self.entries)

    def total_reclaimable_bytes(self) -> int:
        if self._total_reclaimable_bytes_override is not None:
            return self._total_reclaimable_bytes_override
        return estimated_reclaimable_bytes(self.entries)

    def total_shared_bytes(self) -> int:
        if self._total_shared_bytes_override is not None:
            return self._total_shared_bytes_override
        return unique_shared_bytes(self.entries)

    def unknown_reclaimable_entries(self) -> int:
        if self._unknown_reclaimable_entries_override is not None:
            return self._unknown_reclaimable_entries_override
        return sum(e.reclaimable_bytes is None for e in self.entries)

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
            return e.display_bytes >= min_size

        return Report(
            entries=[e for e in self.entries if keep(e)],
            scanned_at=self.scanned_at,
            hostname=self.hostname,
            platform=self.platform,
            note=self.note,
            skipped_paths=list(self.skipped_paths),
            diagnostics=list(self.diagnostics),
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
                "footprint_bytes": e.footprint_bytes,
                "reclaimable_bytes": e.reclaimable_bytes,
                "shared_bytes": e.shared_bytes,
                "usage_explicit": e.usage is not None,
                "mtime": e.mtime,
                "risk": e.risk.value,
                "recipe": e.recipe_lines(),
                "actions": [cleanup_action_to_dict(action) for action in e.actions],
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
                "footprint_bytes": pt.footprint_bytes,
                "reclaimable_bytes": pt.reclaimable_bytes,
                "shared_bytes": pt.shared_bytes,
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
            "total_footprint_bytes": self.total_footprint_bytes(),
            "total_reclaimable_bytes": self.total_reclaimable_bytes(),
            "total_shared_bytes": self.total_shared_bytes(),
            "unknown_reclaimable_entries": self.unknown_reclaimable_entries(),
            "entry_count": len(self.entries),
            "per_provider": per_provider_payload,
            "entries": entries_payload,
            "skipped_paths": list(self.skipped_paths),
            "diagnostics": list(self.diagnostics),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, data: str) -> Report:
        payload = json.loads(data)
        # `entries` may be `null` for auto-snapshots. Callers expecting a list
        # get an empty list — iterating an auto-snapshot's entries is legal
        # but yields nothing.
        raw_entries = payload.get("entries") or []
        entries: list[Entry] = []
        for e in raw_entries:
            raw_actions = e.get("actions") or []
            actions = tuple(
                action
                for raw_action in raw_actions
                if (action := cleanup_action_from_dict(raw_action)) is not None
            )
            has_usage = (
                bool(e["usage_explicit"])
                if "usage_explicit" in e
                else any(
                    key in e for key in ("footprint_bytes", "reclaimable_bytes", "shared_bytes")
                )
            )
            usage = (
                DiskUsage(
                    footprint_bytes=e.get("footprint_bytes"),
                    reclaimable_bytes=e.get("reclaimable_bytes"),
                    shared_bytes=int(e.get("shared_bytes", 0)),
                )
                if has_usage
                else None
            )
            entries.append(
                Entry(
                    provider=e["provider"],
                    id=e["id"],
                    path=Path(e["path"]) if e["path"] is not None else None,
                    label=e["label"],
                    size_bytes=e["size_bytes"],
                    mtime=e["mtime"],
                    risk=Risk(e["risk"]),
                    recipe=list(e["recipe"]),
                    usage=usage,
                    actions=actions,
                    uid=e.get("uid"),
                    gid=e.get("gid"),
                    mode=e.get("mode"),
                    owner=e.get("owner"),
                    group=e.get("group"),
                    perms=e.get("perms"),
                )
            )
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
                footprint_bytes=pt.get("footprint_bytes"),
                reclaimable_bytes=pt.get("reclaimable_bytes"),
                shared_bytes=int(pt.get("shared_bytes", 0)),
            )
            for pt in per_provider_raw
        ]

        # Trust the persisted total_bytes (auto snapshots persist entries=null
        # but always emit a correct total_bytes). v1 files that predate the
        # field fall back to summing the persisted entries.
        total_bytes_raw = payload.get("total_bytes")
        total_bytes_override = int(total_bytes_raw) if isinstance(total_bytes_raw, int) else None
        total_footprint_raw = payload.get("total_footprint_bytes")
        total_reclaimable_raw = payload.get("total_reclaimable_bytes")
        total_shared_raw = payload.get("total_shared_bytes")
        unknown_reclaimable_raw = payload.get("unknown_reclaimable_entries")

        return cls(
            entries=entries,
            scanned_at=datetime.fromisoformat(payload["scanned_at"]),
            hostname=payload["hostname"],
            platform=payload["platform"],
            note=payload.get("note"),
            skipped_paths=list(payload.get("skipped_paths", [])),
            # Additive field: snapshots written before diagnostics existed have
            # no key, so default to [] to keep old snapshots loadable.
            diagnostics=list(payload.get("diagnostics", [])),
            kind=kind,
            started_at=started_at,
            duration_ms=payload.get("duration_ms"),
            per_provider=per_provider,
            _total_bytes_override=total_bytes_override,
            _total_footprint_bytes_override=(
                int(total_footprint_raw)
                if isinstance(total_footprint_raw, int)
                else total_bytes_override
            ),
            _total_reclaimable_bytes_override=(
                int(total_reclaimable_raw)
                if isinstance(total_reclaimable_raw, int)
                else total_bytes_override
            ),
            _total_shared_bytes_override=(
                int(total_shared_raw) if isinstance(total_shared_raw, int) else 0
            ),
            _unknown_reclaimable_entries_override=(
                int(unknown_reclaimable_raw) if isinstance(unknown_reclaimable_raw, int) else 0
            ),
        )


# Choice letters: y=yes, n=no, a=all-remaining-in-provider, s=skip-provider, q=quit
Choice = Literal["y", "n", "a", "s", "q"]
PromptChoice = Callable[[Entry], Choice]
Confirm = Callable[[str], bool]

AsyncPromptChoice = Callable[[Entry], Awaitable[Choice]]
AsyncConfirm = Callable[[str], Awaitable[bool]]
AsyncRunLine = Callable[[tuple[str, ...]], Awaitable[ShellResult]]
