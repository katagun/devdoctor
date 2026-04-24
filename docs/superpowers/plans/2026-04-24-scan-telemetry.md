# Scan telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture scan durations (total + per-provider), persist every explicit scan as an auto-snapshot (lightweight, `entries: null`), and show a median-based static ETA next to the "scanning…" indicator. Snapshots page renders auto and manual in one time-ordered list, auto rows dimmer with a clock+duration suffix.

**Architecture:** Bump `SNAPSHOT_SCHEMA_VERSION` to 2. Extend the `Report` dataclass with `kind`, `started_at`, `duration_ms`, `per_provider`. Instrument `discovery.scan` to record timings. Add a `?snapshot=true` query param to `/api/scan` that writes an auto-snapshot and prunes old ones (retention = 50). Filenames gain a `--auto.json` / `--manual.json` suffix so retention can glob without parsing. Update diff to use per-provider totals when available, falling back to entry sums for v1 files. Frontend adds `useScanETA` (median of recent auto-snapshots scoped to enabled providers) and renders the estimate.

**Tech Stack:** Python 3.12 + pytest (backend), TypeScript + React 18 + Vitest + Tailwind 4 (frontend). No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-04-24-scan-telemetry-design.md`

**Working directory for every command below:** the worktree the executor creates (e.g. `/Users/shamil/projects/github/katagun/diskdoctor/.worktrees/scan-telemetry`). Backend commands run from the repo root; frontend commands from `web/` inside the worktree. Assume `uv sync --extra dev --extra web` and `npm install` have been run.

---

## Task 1: Extend `Report` with telemetry fields + serialization (TDD)

**Files:**
- Modify: `src/diskdoctor/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_types.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.types import (
    Entry,
    ProviderTiming,
    Report,
    Risk,
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotKind,
)


def _entry(provider: str = "p", size: int = 100) -> Entry:
    return Entry(
        provider=provider,
        id=f"{provider}-1",
        path=Path("/tmp/x"),
        label=str(Path("/tmp/x")),
        size_bytes=size,
        mtime=1700000000.0,
        risk=Risk.SAFE,
        recipe=["rm -rf /tmp/x"],
    )


def _report(**overrides) -> Report:
    base = {
        "entries": [_entry()],
        "scanned_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        "hostname": "h",
        "platform": "darwin",
    }
    base.update(overrides)
    return Report(**base)


def test_schema_version_is_2() -> None:
    assert SNAPSHOT_SCHEMA_VERSION == 2


def test_report_defaults_preserve_manual_kind() -> None:
    r = _report()
    assert r.kind == SnapshotKind.MANUAL
    assert r.started_at is None
    assert r.duration_ms is None
    assert r.per_provider == []


def test_manual_round_trip_emits_full_entries() -> None:
    started = datetime(2026, 4, 24, 11, 59, 58, tzinfo=UTC)
    r = _report(
        started_at=started,
        duration_ms=1234,
        per_provider=[ProviderTiming(name="p", bytes=100, entries=1, duration_ms=1234)],
    )
    raw = r.to_json()
    import json
    payload = json.loads(raw)
    assert payload["schema_version"] == 2
    assert payload["kind"] == "manual"
    assert payload["started_at"] == started.isoformat()
    assert payload["duration_ms"] == 1234
    assert payload["total_bytes"] == 100
    assert payload["entry_count"] == 1
    assert payload["per_provider"] == [
        {"name": "p", "bytes": 100, "entries": 1, "duration_ms": 1234}
    ]
    assert isinstance(payload["entries"], list) and len(payload["entries"]) == 1

    restored = Report.from_json(raw)
    assert restored.kind == SnapshotKind.MANUAL
    assert restored.started_at == started
    assert restored.duration_ms == 1234
    assert restored.per_provider == r.per_provider
    assert restored.entries == r.entries


def test_auto_round_trip_omits_entries() -> None:
    r = _report(
        kind=SnapshotKind.AUTO,
        started_at=datetime(2026, 4, 24, 11, 59, 58, tzinfo=UTC),
        duration_ms=500,
        per_provider=[ProviderTiming(name="p", bytes=100, entries=1, duration_ms=500)],
    )
    raw = r.to_json()
    import json
    payload = json.loads(raw)
    assert payload["kind"] == "auto"
    assert payload["entries"] is None
    # total_bytes and entry_count are still emitted.
    assert payload["total_bytes"] == 100
    assert payload["entry_count"] == 1

    restored = Report.from_json(raw)
    assert restored.kind == SnapshotKind.AUTO
    # from_json normalizes `entries: null` into an empty list so callers that
    # iterate `entries` still work.
    assert restored.entries == []


def test_v1_snapshot_deserializes_as_manual_without_timings() -> None:
    import json
    payload = {
        "schema_version": 1,
        "entries": [],
        "scanned_at": "2026-04-24T12:00:00+00:00",
        "hostname": "h",
        "platform": "darwin",
        "note": None,
        "skipped_paths": [],
    }
    restored = Report.from_json(json.dumps(payload))
    assert restored.kind == SnapshotKind.MANUAL
    assert restored.started_at is None
    assert restored.duration_ms is None
    assert restored.per_provider == []


def test_filter_preserves_kind_and_timings() -> None:
    started = datetime(2026, 4, 24, 11, 59, 58, tzinfo=UTC)
    r = _report(
        kind=SnapshotKind.AUTO,
        started_at=started,
        duration_ms=777,
        per_provider=[ProviderTiming(name="p", bytes=100, entries=1, duration_ms=777)],
    )
    filtered = r.filter(min_size=50)
    assert filtered.kind == SnapshotKind.AUTO
    assert filtered.started_at == started
    assert filtered.duration_ms == 777
    assert filtered.per_provider == r.per_provider
```

- [ ] **Step 2: Run and watch them fail**

Run:
```bash
cd <worktree>
uv run pytest tests/test_types.py -v 2>&1 | tail
```

Expected: FAIL — `SnapshotKind`, `ProviderTiming`, and the new `Report` fields don't exist yet.

- [ ] **Step 3: Bump the schema version + add the enum + timing dataclass**

Edit `src/diskdoctor/types.py`.

Find:

```python
SNAPSHOT_SCHEMA_VERSION = 1
```

Change to:

```python
SNAPSHOT_SCHEMA_VERSION = 2
```

Immediately after the `Risk(StrEnum)` definition, add:

```python
class SnapshotKind(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


@dataclass(frozen=True)
class ProviderTiming:
    name: str
    bytes: int
    entries: int
    duration_ms: int
```

- [ ] **Step 4: Extend `Report` with the new fields**

Find the `Report` dataclass definition:

```python
@dataclass
class Report:
    entries: list[Entry]
    scanned_at: datetime
    hostname: str
    platform: str
    note: str | None = None
    skipped_paths: list[str] = field(default_factory=list)
```

Replace with:

```python
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
```

- [ ] **Step 5: Propagate new fields through `.filter()`**

Find the `return Report(...)` inside `Report.filter`:

```python
        return Report(
            entries=[e for e in self.entries if keep(e)],
            scanned_at=self.scanned_at,
            hostname=self.hostname,
            platform=self.platform,
            note=self.note,
            skipped_paths=list(self.skipped_paths),
        )
```

Replace with:

```python
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
```

- [ ] **Step 6: Update `to_json` to emit the new fields**

Find the `to_json` method. Replace its body with:

```python
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
```

- [ ] **Step 7: Update `from_json` to parse the new fields (with v1 backward-compat)**

Find the `from_json` class method. Replace its body with:

```python
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
```

- [ ] **Step 8: Run the tests and watch them pass**

Run:
```bash
cd <worktree>
uv run pytest tests/test_types.py -v 2>&1 | tail
```

Expected: PASS — 5 new tests plus the existing ones.

- [ ] **Step 9: Run the full backend suite**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS — no regressions. Old tests that construct `Report` without the new fields keep passing because they default to manual + None/empty.

- [ ] **Step 10: Commit**

```bash
cd <worktree>
git add src/diskdoctor/types.py tests/test_types.py
git commit -m "feat(types): Report gains kind + timing fields; schema v2

SnapshotKind enum + ProviderTiming dataclass.
Report gains kind, started_at, duration_ms, per_provider (all optional).
to_json emits kind, total_bytes, entry_count, and null entries for auto.
from_json handles both v1 and v2; .filter() preserves new fields."
```

---

## Task 2: Instrument `discovery.scan` with timings (TDD)

**Files:**
- Modify: `src/diskdoctor/discovery.py`
- Modify: `tests/test_discovery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_discovery.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor import discovery
from diskdoctor.providers.base import Provider
from diskdoctor.types import Entry, Risk, ScanFilters, SnapshotKind


class _FakeProvider(Provider):
    """Minimal Provider that returns a fixed list of Entries."""
    name = "fake"
    description = "fake"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = None

    def __init__(self, shell=None, entries=None, name: str = "fake") -> None:
        self._shell = shell
        self._entries = entries or []
        self.name = name  # type: ignore[misc]

    def available(self) -> bool:
        return True

    def discover(self) -> list[Entry]:
        return list(self._entries)


def _e(provider: str = "fake", size: int = 100) -> Entry:
    return Entry(
        provider=provider,
        id=f"{provider}-1",
        path=Path("/tmp/x"),
        label="/tmp/x",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
    )


def test_scan_returns_timing_fields() -> None:
    p = _FakeProvider(entries=[_e(size=100)])
    report = discovery.scan([p], ScanFilters(), datetime.now(UTC))
    assert report.started_at is not None
    assert report.duration_ms is not None
    assert report.duration_ms >= 0
    assert report.kind == SnapshotKind.MANUAL  # discovery.scan defaults to manual


def test_scan_per_provider_row_per_available_provider() -> None:
    p1 = _FakeProvider(name="a", entries=[_e(provider="a", size=100), _e(provider="a", size=200)])
    p2 = _FakeProvider(name="b", entries=[_e(provider="b", size=500)])
    report = discovery.scan([p1, p2], ScanFilters(), datetime.now(UTC))
    names = [pt.name for pt in report.per_provider]
    assert set(names) == {"a", "b"}
    timings = {pt.name: pt for pt in report.per_provider}
    assert timings["a"].bytes == 300
    assert timings["a"].entries == 2
    assert timings["a"].duration_ms >= 0
    assert timings["b"].bytes == 500
    assert timings["b"].entries == 1


def test_scan_skips_unavailable_providers_in_timings() -> None:
    class _Unavailable(_FakeProvider):
        def available(self) -> bool:
            return False

    avail = _FakeProvider(name="a", entries=[_e(provider="a")])
    unavail = _Unavailable(name="b", entries=[_e(provider="b")])
    report = discovery.scan([avail, unavail], ScanFilters(), datetime.now(UTC))
    names = [pt.name for pt in report.per_provider]
    assert names == ["a"]
```

- [ ] **Step 2: Run the tests and watch them fail**

Run:
```bash
cd <worktree>
uv run pytest tests/test_discovery.py -v 2>&1 | tail
```

Expected: FAIL — the `scan` function doesn't set timing fields yet.

- [ ] **Step 3: Replace the `scan` implementation**

Replace the contents of `src/diskdoctor/discovery.py` with:

```python
from __future__ import annotations

import socket
import sys
import time
from datetime import UTC, datetime

from diskdoctor.providers.base import Provider
from diskdoctor.types import ProviderTiming, Report, ScanFilters, SnapshotKind


def scan(
    providers: list[Provider],
    filters: ScanFilters,
    now: datetime,
) -> Report:
    """Run every available provider, collect entries, apply filters, sort.

    Records per-provider and total durations via time.monotonic() so the
    timings are immune to NTP adjustments mid-scan. The returned Report
    has kind=MANUAL by default; the API layer overrides to AUTO when it's
    about to write an auto-snapshot.
    """
    started_at = datetime.now(UTC)
    entries = []
    per_provider: list[ProviderTiming] = []
    for p in providers:
        if not p.available():
            continue
        t0 = time.monotonic()
        provider_entries = p.discover()
        dt_ms = int((time.monotonic() - t0) * 1000)
        entries.extend(provider_entries)
        per_provider.append(
            ProviderTiming(
                name=p.name,
                bytes=sum(e.size_bytes for e in provider_entries),
                entries=len(provider_entries),
                duration_ms=dt_ms,
            )
        )
    scanned_at = datetime.now(UTC)
    duration_ms = int((scanned_at - started_at).total_seconds() * 1000)

    entries.sort(key=lambda e: e.size_bytes, reverse=True)

    report = Report(
        entries=entries,
        scanned_at=scanned_at,
        hostname=socket.gethostname(),
        platform=_platform(),
        kind=SnapshotKind.MANUAL,
        started_at=started_at,
        duration_ms=duration_ms,
        per_provider=per_provider,
    )

    if filters.min_size_bytes or filters.risks is not None or filters.providers is not None:
        report = report.filter(
            risks=filters.risks,
            min_size=filters.min_size_bytes,
            providers=filters.providers,
        )

    return report


def _platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform
```

Notes:
- The `now` argument is kept in the signature for API compatibility with existing callers, but we use wall-clock `datetime.now(UTC)` internally for `started_at` / `scanned_at`. The `now` parameter is effectively ignored; tests that passed in a fixed datetime will still pass but should be aware timing happens in real time. This matches how tests were already using the parameter (not asserting on it).

- [ ] **Step 4: Run the tests and watch them pass**

Run:
```bash
cd <worktree>
uv run pytest tests/test_discovery.py -v 2>&1 | tail
```

Expected: PASS — 3 new tests + existing discovery tests.

- [ ] **Step 5: Run the full backend suite**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd <worktree>
git add src/diskdoctor/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): instrument scan with per-provider + total durations

Uses time.monotonic() for duration deltas (NTP-safe) and wall-clock UTC
for started_at/scanned_at (display-ready). kind defaults to MANUAL; the
API layer overrides to AUTO when writing an auto-snapshot."
```

---

## Task 3: History module — filename convention, retention, kind-aware diff (TDD)

**Files:**
- Modify: `src/diskdoctor/history.py`
- Modify: `tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_history.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor import history
from diskdoctor.types import (
    Entry,
    ProviderTiming,
    Report,
    Risk,
    SnapshotKind,
)


def _entry(provider: str = "p", size: int = 100) -> Entry:
    return Entry(
        provider=provider,
        id=f"{provider}-1",
        path=Path("/tmp/x"),
        label="/tmp/x",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
    )


def _report(kind: SnapshotKind, scanned_at: datetime, entries=None, per_provider=None) -> Report:
    return Report(
        entries=entries or [_entry()],
        scanned_at=scanned_at,
        hostname="h",
        platform="darwin",
        kind=kind,
        started_at=scanned_at,
        duration_ms=100,
        per_provider=per_provider or [ProviderTiming(name="p", bytes=100, entries=1, duration_ms=100)],
    )


def test_write_snapshot_uses_kind_suffix(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 24, 12, 0, 5, tzinfo=UTC)
    manual = _report(SnapshotKind.MANUAL, ts)
    auto = _report(SnapshotKind.AUTO, ts.replace(second=10))

    mp = history.write_snapshot(manual, tmp_path)
    ap = history.write_snapshot(auto, tmp_path)

    assert mp.name.endswith("--manual.json")
    assert ap.name.endswith("--auto.json")


def test_write_snapshot_auto_has_null_entries_on_disk(tmp_path: Path) -> None:
    import json
    ts = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    auto = _report(SnapshotKind.AUTO, ts)
    path = history.write_snapshot(auto, tmp_path)
    payload = json.loads(path.read_text())
    assert payload["kind"] == "auto"
    assert payload["entries"] is None
    # Sanity: per_provider and total_bytes are present.
    assert payload["per_provider"][0]["name"] == "p"
    assert payload["total_bytes"] == 100


def test_prune_auto_snapshots_keeps_newest(tmp_path: Path) -> None:
    # Create 5 auto files with ascending timestamps.
    for i in range(5):
        ts = datetime(2026, 4, 24, 12, 0, i, tzinfo=UTC)
        history.write_snapshot(_report(SnapshotKind.AUTO, ts), tmp_path)
    # And 2 manual files — these must NEVER be touched.
    for i in range(2):
        ts = datetime(2026, 4, 24, 13, 0, i, tzinfo=UTC)
        history.write_snapshot(_report(SnapshotKind.MANUAL, ts), tmp_path)

    deleted = history.prune_auto_snapshots(tmp_path, keep=3)
    assert len(deleted) == 2

    remaining_autos = sorted(p.name for p in tmp_path.glob("*--auto.json"))
    # Newest 3 of the 5 auto files remain. Timestamps 2/3/4 (0-indexed).
    assert len(remaining_autos) == 3
    assert all("2026-04-24T12-00-0" in n for n in remaining_autos)

    remaining_manuals = sorted(p.name for p in tmp_path.glob("*--manual.json"))
    assert len(remaining_manuals) == 2  # untouched


def test_prune_auto_with_zero_keep_removes_all_autos(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    history.write_snapshot(_report(SnapshotKind.AUTO, ts), tmp_path)
    history.write_snapshot(_report(SnapshotKind.MANUAL, ts.replace(minute=1)), tmp_path)
    deleted = history.prune_auto_snapshots(tmp_path, keep=0)
    assert len(deleted) == 1
    assert list(tmp_path.glob("*--auto.json")) == []
    assert len(list(tmp_path.glob("*--manual.json"))) == 1


def test_prune_auto_on_missing_dir_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert history.prune_auto_snapshots(missing) == []


def test_diff_uses_per_provider_totals_when_available() -> None:
    """Auto-snapshots have entries=null but per_provider totals. Diff must use those."""
    ts1 = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    ts2 = datetime(2026, 4, 24, 13, 0, tzinfo=UTC)
    before = Report(
        entries=[],  # auto has no entries
        scanned_at=ts1, hostname="h", platform="darwin",
        kind=SnapshotKind.AUTO, started_at=ts1, duration_ms=10,
        per_provider=[ProviderTiming("p", 1000, 1, 10)],
    )
    after = Report(
        entries=[],
        scanned_at=ts2, hostname="h", platform="darwin",
        kind=SnapshotKind.AUTO, started_at=ts2, duration_ms=10,
        per_provider=[ProviderTiming("p", 600, 1, 10)],
    )
    report = history.diff(before, after)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.provider == "p"
    assert row.before_bytes == 1000
    assert row.after_bytes == 600
    assert row.delta_bytes == -400


def test_diff_mixed_auto_manual_symmetric() -> None:
    """auto before, manual after: totals from per_provider vs entries must match."""
    ts1 = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    ts2 = datetime(2026, 4, 24, 13, 0, tzinfo=UTC)
    before = Report(
        entries=[],
        scanned_at=ts1, hostname="h", platform="darwin",
        kind=SnapshotKind.AUTO, started_at=ts1, duration_ms=10,
        per_provider=[ProviderTiming("p", 1000, 1, 10)],
    )
    after = Report(
        entries=[_entry(size=700)],
        scanned_at=ts2, hostname="h", platform="darwin",
        kind=SnapshotKind.MANUAL, started_at=ts2, duration_ms=10,
        per_provider=[ProviderTiming("p", 700, 1, 10)],
    )
    report = history.diff(before, after)
    assert report.rows[0].before_bytes == 1000
    assert report.rows[0].after_bytes == 700
    assert report.rows[0].delta_bytes == -300


def test_diff_v1_manual_report_falls_back_to_summing_entries() -> None:
    """Pre-feature snapshots have per_provider=[] but do have entries. Diff must still work."""
    ts1 = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    ts2 = datetime(2026, 4, 24, 13, 0, tzinfo=UTC)
    # v1-shaped: no per_provider, kind=manual (default), has entries.
    before = Report(
        entries=[_entry(size=500)],
        scanned_at=ts1, hostname="h", platform="darwin",
    )
    after = Report(
        entries=[_entry(size=300)],
        scanned_at=ts2, hostname="h", platform="darwin",
    )
    report = history.diff(before, after)
    assert report.rows[0].before_bytes == 500
    assert report.rows[0].after_bytes == 300
    assert report.rows[0].delta_bytes == -200
```

- [ ] **Step 2: Run and watch them fail**

Run:
```bash
cd <worktree>
uv run pytest tests/test_history.py -v 2>&1 | tail
```

Expected: FAIL — `prune_auto_snapshots` doesn't exist; filenames don't have the suffix; diff uses entries.

- [ ] **Step 3: Update `write_snapshot` to include the kind suffix**

Edit `src/diskdoctor/history.py`. Replace `write_snapshot` with:

```python
def write_snapshot(report: Report, directory: Path) -> Path:
    """Write a snapshot atomically.

    Filename includes a --<kind>.json suffix so retention (and Snapshot-page
    filtering) can glob without reading contents.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.scanned_at.strftime("%Y-%m-%dT%H-%M-%S")
    target = directory / f"{stamp}--{report.kind.value}.json"
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(report.to_json())
        os.replace(tmp, target)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return target
```

Also update the import of `Report` at the top to include `SnapshotKind`:

```python
from diskdoctor.types import DiffReport, DiffRow, Report, SnapshotKind
```

- [ ] **Step 4: Add `prune_auto_snapshots`**

After `write_snapshot` and before `load_snapshot`, add:

```python
AUTO_SNAPSHOT_RETENTION = 50


def prune_auto_snapshots(directory: Path, keep: int = AUTO_SNAPSHOT_RETENTION) -> list[Path]:
    """Delete oldest auto-snapshots beyond ``keep``. Manual snapshots are
    never touched; pre-feature (v1) snapshots without a kind suffix aren't
    matched by the ``*--auto.json`` glob and so are also safe.

    Returns the list of deleted paths (for logging / tests).
    """
    if not directory.exists():
        return []
    autos = sorted(directory.glob("*--auto.json"), reverse=True)  # newest first
    victims = autos[keep:]
    deleted: list[Path] = []
    for p in victims:
        try:
            p.unlink()
            deleted.append(p)
        except (FileNotFoundError, PermissionError):
            pass
    return deleted
```

- [ ] **Step 5: Replace `diff` to use per-provider totals when available**

Find the current `diff` function:

```python
def diff(before: Report, after: Report) -> DiffReport:
    before_by = {p: sum(e.size_bytes for e in es) for p, es in before.by_provider().items()}
    after_by = {p: sum(e.size_bytes for e in es) for p, es in after.by_provider().items()}
    ...
```

Replace with:

```python
def _totals_by_provider(report: Report) -> dict[str, int]:
    """Prefer per_provider totals (v2) when present; fall back to summing
    entries (v1 files, or any Report built without timings). Returns a
    provider-name → bytes dict covering every provider seen in the report.
    """
    if report.per_provider:
        return {pt.name: pt.bytes for pt in report.per_provider}
    return {p: sum(e.size_bytes for e in es) for p, es in report.by_provider().items()}


def diff(before: Report, after: Report) -> DiffReport:
    before_by = _totals_by_provider(before)
    after_by = _totals_by_provider(after)
    providers = sorted(set(before_by) | set(after_by))
    rows: list[DiffRow] = []
    for name in providers:
        b = before_by.get(name, 0)
        a = after_by.get(name, 0)
        delta = a - b
        pct = 0.0 if b == 0 else (delta / b) * 100.0
        rows.append(
            DiffRow(
                provider=name,
                before_bytes=b,
                after_bytes=a,
                delta_bytes=delta,
                delta_pct=pct,
            )
        )
    return DiffReport(before_at=before.scanned_at, after_at=after.scanned_at, rows=rows)
```

- [ ] **Step 6: Also update `latest_snapshots` to glob both suffixes**

Find `latest_snapshots`:

```python
def latest_snapshots(directory: Path, n: int = 2) -> list[Path]:
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.json"))
    return files[-n:]
```

This stays unchanged — `*.json` still matches both `--auto.json` and `--manual.json` (and v1 bare filenames). No edit needed. (Written here so the plan executor knows to verify rather than assume it needs changing.)

- [ ] **Step 7: Run the tests and watch them pass**

Run:
```bash
cd <worktree>
uv run pytest tests/test_history.py -v 2>&1 | tail
```

Expected: PASS — new tests + existing pass.

- [ ] **Step 8: Run the full backend suite**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd <worktree>
git add src/diskdoctor/history.py tests/test_history.py
git commit -m "feat(history): kind-suffixed filenames, prune_auto_snapshots, kind-aware diff

Snapshot filenames gain --<kind>.json suffix so retention globs don't
need to parse contents. New prune_auto_snapshots(keep=50) trims oldest
auto-snapshots; manual files never touched. Diff uses per_provider
totals when available (auto-snapshots, v2 manuals) and falls back to
summing entries for v1 files."
```

---

## Task 4: `/api/scan` gains `?snapshot=true` (TDD)

**Files:**
- Modify: `src/diskdoctor/web/routes_scan.py`
- Modify: `tests/web/test_routes_scan.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_routes_scan.py`:

```python
def test_scan_without_snapshot_flag_writes_nothing(tmp_path, monkeypatch) -> None:
    """Default /api/scan does not persist a snapshot."""
    from diskdoctor import history
    from fastapi.testclient import TestClient
    from diskdoctor.web.app import create_app

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/scan")
    assert resp.status_code == 200
    assert list(tmp_path.glob("*.json")) == []


def test_scan_with_snapshot_flag_writes_auto(tmp_path, monkeypatch) -> None:
    """/api/scan?snapshot=true writes an auto-snapshot with --auto.json suffix."""
    from diskdoctor import history
    from fastapi.testclient import TestClient
    from diskdoctor.web.app import create_app

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/scan?snapshot=true")
    assert resp.status_code == 200
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert files[0].name.endswith("--auto.json")


def test_scan_with_snapshot_flag_prunes_to_retention(tmp_path, monkeypatch) -> None:
    """If there are already 60 auto-snapshots, a new one triggers pruning to 50."""
    from datetime import UTC, datetime
    from diskdoctor import history
    from diskdoctor.types import ProviderTiming, Report, SnapshotKind
    from fastapi.testclient import TestClient
    from diskdoctor.web.app import create_app

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)
    # Also cap retention low so the test doesn't need to create 50+ files.
    monkeypatch.setattr(history, "AUTO_SNAPSHOT_RETENTION", 3)

    # Seed 5 existing auto-snapshots.
    for i in range(5):
        ts = datetime(2026, 4, 24, 10, 0, i, tzinfo=UTC)
        r = Report(
            entries=[], scanned_at=ts, hostname="h", platform="darwin",
            kind=SnapshotKind.AUTO, started_at=ts, duration_ms=10,
            per_provider=[ProviderTiming("p", 0, 0, 10)],
        )
        history.write_snapshot(r, tmp_path)

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/scan?snapshot=true")
    assert resp.status_code == 200
    remaining = sorted(p.name for p in tmp_path.glob("*--auto.json"))
    # After the new write there are 6 files; prune(keep=3) leaves 3.
    assert len(remaining) == 3
```

If existing tests in the file do not import `create_app` / `TestClient`, follow the existing import pattern in that file — this block assumes them; adjust as needed.

- [ ] **Step 2: Run the tests and watch them fail**

Run:
```bash
cd <worktree>
uv run pytest tests/web/test_routes_scan.py -v 2>&1 | tail
```

Expected: FAIL — `snapshot=true` isn't handled; no write happens.

- [ ] **Step 3: Update `/api/scan` to accept the flag**

Edit `src/diskdoctor/web/routes_scan.py`. Find the `scan` route:

```python
@router.get("/scan")
def scan(
    request: Request,
    min_size: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    provider: str | None = Query(default=None),
) -> JSONResponse:
    filters = ScanFilters(
        min_size_bytes=_parse_size(min_size) if min_size else 0,
        risks=_parse_risks(risk),
        providers=frozenset(provider.split(",")) if provider else None,
    )
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, filters, datetime.now(UTC))
    return JSONResponse(content=_report_to_dict(report))
```

Replace with:

```python
@router.get("/scan")
def scan(
    request: Request,
    min_size: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    snapshot: bool = Query(default=False),
) -> JSONResponse:
    filters = ScanFilters(
        min_size_bytes=_parse_size(min_size) if min_size else 0,
        risks=_parse_risks(risk),
        providers=frozenset(provider.split(",")) if provider else None,
    )
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, filters, datetime.now(UTC))
    if snapshot:
        import dataclasses
        from diskdoctor import history
        from diskdoctor.types import SnapshotKind

        auto_report = dataclasses.replace(report, kind=SnapshotKind.AUTO)
        try:
            history.write_snapshot(auto_report, history.default_snapshot_dir())
            history.prune_auto_snapshots(history.default_snapshot_dir())
        except OSError:
            # Disk full / permission denied / whatever — don't fail the
            # scan response because the auto-snapshot write choked. The
            # client still gets the scan; the next scan will try again.
            pass
    return JSONResponse(content=_report_to_dict(report))
```

- [ ] **Step 4: Run the tests and watch them pass**

Run:
```bash
cd <worktree>
uv run pytest tests/web/test_routes_scan.py -v 2>&1 | tail
```

Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd <worktree>
git add src/diskdoctor/web/routes_scan.py tests/web/test_routes_scan.py
git commit -m "feat(api): /api/scan?snapshot=true writes an auto-snapshot

Auto-snapshot kind is constructed via dataclasses.replace so the in-
memory report returned to the client stays MANUAL (prevents accidental
reuse with the auto shape). OSError during write/prune is swallowed —
scan response must not fail because the auto-snapshot write choked."
```

---

## Task 5: `/api/snapshots` gains `?kind` + `?limit`; `SnapshotMeta` extended (TDD)

**Files:**
- Modify: `src/diskdoctor/web/models.py`
- Modify: `src/diskdoctor/web/routes_history.py`
- Modify: `tests/web/test_routes_history.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_routes_history.py`:

```python
def test_snapshots_listing_includes_kind_and_duration(tmp_path, monkeypatch) -> None:
    from datetime import UTC, datetime
    from diskdoctor import history
    from diskdoctor.types import ProviderTiming, Report, SnapshotKind
    from fastapi.testclient import TestClient
    from diskdoctor.web.app import create_app

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)

    ts = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    auto = Report(
        entries=[], scanned_at=ts, hostname="h", platform="darwin",
        kind=SnapshotKind.AUTO, started_at=ts, duration_ms=4821,
        per_provider=[ProviderTiming("p", 100, 1, 4821)],
    )
    history.write_snapshot(auto, tmp_path)

    client = TestClient(create_app())
    resp = client.get("/api/snapshots")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["kind"] == "auto"
    assert row["duration_ms"] == 4821
    assert row["entry_count"] == 0
    assert row["per_provider"] == [
        {"name": "p", "bytes": 100, "entries": 1, "duration_ms": 4821}
    ]


def test_snapshots_listing_filters_by_kind(tmp_path, monkeypatch) -> None:
    from datetime import UTC, datetime
    from diskdoctor import history
    from diskdoctor.types import Entry, ProviderTiming, Report, Risk, SnapshotKind
    from fastapi.testclient import TestClient
    from diskdoctor.web.app import create_app
    from pathlib import Path

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)

    def _r(kind: SnapshotKind, second: int) -> Report:
        ts = datetime(2026, 4, 24, 12, 0, second, tzinfo=UTC)
        entries = (
            []
            if kind == SnapshotKind.AUTO
            else [Entry("p", "p-1", Path("/x"), "/x", 0, None, Risk.SAFE, [])]
        )
        return Report(
            entries=entries, scanned_at=ts, hostname="h", platform="darwin",
            kind=kind, started_at=ts, duration_ms=10,
            per_provider=[ProviderTiming("p", 0, 0, 10)],
        )

    history.write_snapshot(_r(SnapshotKind.AUTO, 0), tmp_path)
    history.write_snapshot(_r(SnapshotKind.MANUAL, 1), tmp_path)

    client = TestClient(create_app())

    resp = client.get("/api/snapshots?kind=auto")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["kind"] == "auto"

    resp = client.get("/api/snapshots?kind=manual")
    assert len(resp.json()) == 1
    assert resp.json()[0]["kind"] == "manual"

    resp = client.get("/api/snapshots")  # default = all
    assert len(resp.json()) == 2


def test_snapshots_listing_respects_limit(tmp_path, monkeypatch) -> None:
    from datetime import UTC, datetime
    from diskdoctor import history
    from diskdoctor.types import ProviderTiming, Report, SnapshotKind
    from fastapi.testclient import TestClient
    from diskdoctor.web.app import create_app

    monkeypatch.setattr(history, "default_snapshot_dir", lambda: tmp_path)

    for i in range(5):
        ts = datetime(2026, 4, 24, 12, 0, i, tzinfo=UTC)
        r = Report(
            entries=[], scanned_at=ts, hostname="h", platform="darwin",
            kind=SnapshotKind.AUTO, started_at=ts, duration_ms=10,
            per_provider=[],
        )
        history.write_snapshot(r, tmp_path)

    client = TestClient(create_app())
    resp = client.get("/api/snapshots?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
```

- [ ] **Step 2: Run and watch them fail**

Run:
```bash
cd <worktree>
uv run pytest tests/web/test_routes_history.py -v 2>&1 | tail
```

Expected: FAIL — `kind`, `duration_ms`, `entry_count`, `per_provider` not in response; `?kind` / `?limit` not supported.

- [ ] **Step 3: Extend `SnapshotMeta`**

Edit `src/diskdoctor/web/models.py`. Find `SnapshotMeta`:

```python
class SnapshotMeta(BaseModel):
    name: str
    path: str
    scanned_at: str
    hostname: str
    platform: str
    note: str | None
    total_bytes: int
```

Replace with:

```python
class SnapshotMeta(BaseModel):
    name: str
    path: str
    scanned_at: str
    hostname: str
    platform: str
    note: str | None
    total_bytes: int
    # Telemetry fields. Optional so v1 snapshot files (no kind/timing data)
    # serve as manual with duration_ms=None and empty per_provider.
    kind: Literal["auto", "manual"] = "manual"
    duration_ms: int | None = None
    entry_count: int | None = None
    per_provider: list[dict] | None = None
```

- [ ] **Step 4: Update `/api/snapshots` to support filtering and populate new fields**

Edit `src/diskdoctor/web/routes_history.py`. Find the `list_snapshots` route:

```python
@router.get("/snapshots")
def list_snapshots() -> list[SnapshotMeta]:
    out: list[SnapshotMeta] = []
    directory = history.default_snapshot_dir()
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json"), reverse=True):
        report = Report.from_json(path.read_text())
        out.append(
            SnapshotMeta(
                name=path.name,
                path=str(path),
                scanned_at=report.scanned_at.isoformat(),
                hostname=report.hostname,
                platform=report.platform,
                note=report.note,
                total_bytes=report.total_bytes(),
            )
        )
    return out
```

Replace with:

```python
@router.get("/snapshots")
def list_snapshots(
    limit: int | None = Query(default=None, ge=1),
    kind: Literal["auto", "manual", "all"] = Query(default="all"),
) -> list[SnapshotMeta]:
    out: list[SnapshotMeta] = []
    directory = history.default_snapshot_dir()
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            report = Report.from_json(path.read_text())
        except Exception:
            # Malformed file — skip, don't fail the whole listing.
            continue
        if kind != "all" and report.kind.value != kind:
            continue
        out.append(
            SnapshotMeta(
                name=path.name,
                path=str(path),
                scanned_at=report.scanned_at.isoformat(),
                hostname=report.hostname,
                platform=report.platform,
                note=report.note,
                total_bytes=report.total_bytes(),
                kind=report.kind.value,
                duration_ms=report.duration_ms,
                entry_count=len(report.entries) if report.kind.value == "manual" else None,
                per_provider=[
                    {
                        "name": pt.name,
                        "bytes": pt.bytes,
                        "entries": pt.entries,
                        "duration_ms": pt.duration_ms,
                    }
                    for pt in report.per_provider
                ] if report.per_provider else None,
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out
```

Add `from typing import Literal` and `from fastapi import Query` at the top if not already imported. (Currently `Query` comes through the `APIRouter` import chain; add explicitly if typecheck complains.)

- [ ] **Step 5: Run tests and watch them pass**

Run:
```bash
cd <worktree>
uv run pytest tests/web/test_routes_history.py -v 2>&1 | tail
```

Expected: PASS.

- [ ] **Step 6: Full suite**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add src/diskdoctor/web/models.py src/diskdoctor/web/routes_history.py tests/web/test_routes_history.py
git commit -m "feat(api): /api/snapshots gains ?kind + ?limit; SnapshotMeta telemetry fields

SnapshotMeta carries optional kind, duration_ms, entry_count, per_provider.
Route supports ?kind=auto|manual|all (default all) and ?limit=N (no cap
by default). Malformed files are skipped rather than failing the listing."
```

---

## Task 6: Frontend — `formatMs` helper + `SnapshotMeta` type extension (TDD)

**Files:**
- Modify: `web/src/lib/format.ts`
- Modify: `web/src/hooks/useSnapshots.ts`
- Modify: `web/tests/unit/format.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `web/tests/unit/format.test.ts`:

```ts
import { formatMs } from "@/lib/format";

describe("formatMs", () => {
  it("sub-second values", () => {
    expect(formatMs(0)).toBe("0ms");
    expect(formatMs(45)).toBe("45ms");
    expect(formatMs(999)).toBe("999ms");
  });

  it("seconds", () => {
    expect(formatMs(1000)).toBe("1.0s");
    expect(formatMs(4821)).toBe("4.8s");
    expect(formatMs(59999)).toBe("60.0s"); // rounds up to 60
  });

  it("minutes plus seconds", () => {
    expect(formatMs(60000)).toBe("1m 0s");
    expect(formatMs(75500)).toBe("1m 15s");
    expect(formatMs(3 * 60 * 1000)).toBe("3m 0s");
  });

  it("null / negative / NaN return a dash", () => {
    expect(formatMs(null)).toBe("—");
    expect(formatMs(-5)).toBe("—");
    expect(formatMs(Number.NaN)).toBe("—");
  });
});
```

- [ ] **Step 2: Run and watch fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/format.test.ts
```

Expected: FAIL — `formatMs` is not exported from `@/lib/format`.

- [ ] **Step 3: Implement `formatMs`**

Edit `web/src/lib/format.ts`. Add this function (place it next to `humanBytes`, before `staleness`):

```ts
export function formatMs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const totalSecs = Math.round(ms / 1000);
  const m = Math.floor(totalSecs / 60);
  const s = totalSecs % 60;
  return `${m}m ${s}s`;
}
```

- [ ] **Step 4: Extend `SnapshotMeta` on the client**

Edit `web/src/hooks/useSnapshots.ts`. Find `SnapshotMeta`:

```ts
export interface SnapshotMeta {
  name: string;
  path: string;
  scanned_at: string;
  hostname: string;
  platform: string;
  note: string | null;
  total_bytes: number;
}
```

Replace with:

```ts
export interface ProviderTimingMeta {
  name: string;
  bytes: number;
  entries: number;
  duration_ms: number;
}

export interface SnapshotMeta {
  name: string;
  path: string;
  scanned_at: string;
  hostname: string;
  platform: string;
  note: string | null;
  total_bytes: number;
  // Telemetry — optional / nullable for v1 files.
  kind?: "auto" | "manual";
  duration_ms?: number | null;
  entry_count?: number | null;
  per_provider?: ProviderTimingMeta[] | null;
}
```

Existing consumers that read `name`, `scanned_at`, `total_bytes`, etc. keep working because the new fields are optional.

- [ ] **Step 5: Run tests and watch them pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/format.test.ts
```

Expected: PASS.

- [ ] **Step 6: Full JS suite + typecheck**

Run:
```bash
cd <worktree>/web
npx vitest run
npm run typecheck
```

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/lib/format.ts web/src/hooks/useSnapshots.ts web/tests/unit/format.test.ts
git commit -m "feat(web): formatMs helper + SnapshotMeta telemetry fields

formatMs: <1s → 999ms, <60s → 4.8s, >=60s → 1m 15s, null/negative/NaN → —.
SnapshotMeta optional kind/duration_ms/entry_count/per_provider."
```

---

## Task 7: Frontend — `useScan` explicit flag + `useScanETA` hook (TDD)

**Files:**
- Modify: `web/src/hooks/useScan.ts`
- Create: `web/src/hooks/useScanETA.ts`
- Create: `web/tests/unit/useScanETA.test.ts`
- Modify: `web/src/pages/Scan.tsx` (only the hook-call site, to pass `explicit: true`)

- [ ] **Step 1: Extend `useScan` with an `explicit` option**

Edit `web/src/hooks/useScan.ts`. Find `UseScanOptions`:

```ts
export interface UseScanOptions {
  risk?: string;
  minSize?: string;
  provider?: string;
  staleTime?: number;
  refetchOnMount?: boolean;
}
```

Replace with:

```ts
export interface UseScanOptions {
  risk?: string;
  minSize?: string;
  provider?: string;
  staleTime?: number;
  refetchOnMount?: boolean;
  /** When true, this scan writes an auto-snapshot. Set for the cold page
   * load and explicit "Rescan now"; leave false/undefined for the pending
   * re-fetches TanStack Query performs on its own. */
  explicit?: boolean;
}
```

Then find the query body. Update the URL construction and query key to include the `snapshot=true` flag when `explicit` is true:

```ts
export function useScan(params: UseScanOptions = {}) {
  const { staleTime, refetchOnMount, explicit, ...filters } = params;
  return useQuery({
    queryKey: ["scan", filters, explicit ? "explicit" : "implicit"],
    staleTime,
    refetchOnMount,
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (filters.risk) qs.set("risk", filters.risk);
      if (filters.minSize) qs.set("min_size", filters.minSize);
      if (filters.provider) qs.set("provider", filters.provider);
      if (explicit) qs.set("snapshot", "true");
      const query = qs.toString() ? `?${qs}` : "";
      const raw = await apiFetch<ScanResponse>(`/scan${query}`);
      const rows: CacheTableRow[] = raw.entries.map((e) => ({
        id: e.id,
        provider: e.provider,
        label: e.label,
        path: e.path ?? "—",
        size_bytes: e.size_bytes,
        risk: e.risk,
        mtime: e.mtime,
        recipeHint: e.recipe[0] ?? "",
        owner: e.owner ?? null,
        group: e.group ?? null,
        perms: e.perms ?? null,
      }));
      return {
        rows,
        totalBytes: raw.entries.reduce((a, b) => a + b.size_bytes, 0),
        scannedAt: raw.scanned_at,
      };
    },
  });
}
```

- [ ] **Step 2: Update `Scan.tsx` to pass `explicit: true`**

Open `web/src/pages/Scan.tsx`. Find the single call to `useScan({ ... })`. Add `explicit: true` to the options object. If there's exactly one such call, this is a one-line addition. If the call is split across filter-state/refetch logic, add `explicit: true` alongside the other options.

Concretely: search for `useScan(` and add `explicit: true,` to the options. Keep existing options unchanged.

(Rationale: the Scan page is the only site that should set `explicit: true`. Its single `useScan({ ... })` call suffices — TanStack Query's re-fetch semantics cover both initial mount and "Rescan now" via the same call site.)

- [ ] **Step 3: Write the failing tests for `useScanETA`**

Create `web/tests/unit/useScanETA.test.ts`:

```ts
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Note: useScanETA fetches /api/snapshots?kind=auto&limit=20 via apiFetch,
// so we mock apiFetch to return canned responses per test.

const mockApiFetch = vi.fn();

vi.mock("@/api", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

vi.mock("@/hooks/useSelectedProviders", () => ({
  useSelectedProviders: () => ({
    isEnabled: (name: string) => mockEnabledProviders.has(name),
  }),
}));

let mockEnabledProviders = new Set<string>();

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockApiFetch.mockReset();
  mockEnabledProviders = new Set(["ollama", "hf", "docker"]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useScanETA", () => {
  it("returns null etaMs with fewer than 3 samples", async () => {
    mockApiFetch.mockResolvedValue([]);  // empty listing
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    await waitFor(() => expect(result.current).toBeTruthy());
    expect(result.current.etaMs).toBeNull();
    expect(result.current.sampleSize).toBe(0);
  });

  it("sums medians across enabled providers only", async () => {
    // 3 snapshots, each with per_provider for ollama, hf, docker.
    const fake = [
      {
        name: "a", path: "a", scanned_at: "2026-04-24T12:00:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 500 },
        ],
      },
      {
        name: "b", path: "b", scanned_at: "2026-04-24T12:01:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 2000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 300 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 400 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 700 },
        ],
      },
      {
        name: "c", path: "c", scanned_at: "2026-04-24T12:02:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1500,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 200 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 300 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 600 },
        ],
      },
    ];
    mockApiFetch.mockResolvedValue(fake);
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    await waitFor(() => expect(result.current.etaMs).not.toBeNull());
    // Medians across the 3 snapshots, per provider:
    //   ollama → median(100, 300, 200) = 200
    //   hf     → median(200, 400, 300) = 300
    //   docker → median(500, 700, 600) = 600
    // Sum = 1100.
    expect(result.current.etaMs).toBe(1100);
    expect(result.current.providerCount).toBe(3);
    expect(result.current.sampleSize).toBe(3);
  });

  it("excludes disabled providers from the sum", async () => {
    // User has disabled docker.
    mockEnabledProviders = new Set(["ollama", "hf"]);
    const fake = [
      {
        name: "a", path: "a", scanned_at: "2026-04-24T12:00:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 5000 },
        ],
      },
      {
        name: "b", path: "b", scanned_at: "2026-04-24T12:01:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 2000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 5000 },
        ],
      },
      {
        name: "c", path: "c", scanned_at: "2026-04-24T12:02:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1500,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 5000 },
        ],
      },
    ];
    mockApiFetch.mockResolvedValue(fake);
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    await waitFor(() => expect(result.current.etaMs).not.toBeNull());
    // docker excluded: median(100) + median(200) = 300.
    expect(result.current.etaMs).toBe(300);
    expect(result.current.providerCount).toBe(2);
  });

  it("filters out snapshots with null/missing duration_ms", async () => {
    const fake = [
      // Missing duration_ms — excluded.
      {
        name: "a", path: "a", scanned_at: "2026-04-24T12:00:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: null, per_provider: [],
      },
      {
        name: "b", path: "b", scanned_at: "2026-04-24T12:01:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 500,
        per_provider: [{ name: "ollama", bytes: 0, entries: 0, duration_ms: 100 }],
      },
      {
        name: "c", path: "c", scanned_at: "2026-04-24T12:02:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 600,
        per_provider: [{ name: "ollama", bytes: 0, entries: 0, duration_ms: 200 }],
      },
    ];
    mockApiFetch.mockResolvedValue(fake);
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    // Only 2 usable samples < 3 threshold → etaMs null.
    await waitFor(() => expect(result.current).toBeTruthy());
    expect(result.current.etaMs).toBeNull();
    expect(result.current.sampleSize).toBe(2);
  });
});
```

- [ ] **Step 4: Run the ETA tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useScanETA.test.ts
```

Expected: FAIL — module-resolution error on `@/hooks/useScanETA`.

- [ ] **Step 5: Implement `useScanETA`**

Create `web/src/hooks/useScanETA.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import type { SnapshotMeta } from "@/hooks/useSnapshots";

const MIN_SAMPLES = 3;
const LIMIT = 20;

export interface UseScanETAResult {
  etaMs: number | null;
  providerCount: number;
  sampleSize: number;
}

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const sorted = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function useScanETA(): UseScanETAResult {
  const { isEnabled } = useSelectedProviders();
  const { data } = useQuery({
    queryKey: ["scan-eta", "auto", LIMIT],
    queryFn: () => apiFetch<SnapshotMeta[]>(`/snapshots?kind=auto&limit=${LIMIT}`),
    // Settings for this query: stale-time modest so rapid successive scans
    // use the same sample without refetching on each render.
    staleTime: 30_000,
  });

  if (!data) return { etaMs: null, providerCount: 0, sampleSize: 0 };

  const usable = data.filter(
    (s) => typeof s.duration_ms === "number" && Array.isArray(s.per_provider),
  );
  if (usable.length < MIN_SAMPLES) {
    return { etaMs: null, providerCount: 0, sampleSize: usable.length };
  }

  // Gather per-provider duration arrays, restricted to enabled providers.
  const perProvider = new Map<string, number[]>();
  for (const snap of usable) {
    for (const pt of snap.per_provider ?? []) {
      if (!isEnabled(pt.name)) continue;
      const arr = perProvider.get(pt.name) ?? [];
      arr.push(pt.duration_ms);
      perProvider.set(pt.name, arr);
    }
  }

  let etaMs = 0;
  for (const durations of perProvider.values()) {
    etaMs += median(durations);
  }

  return {
    etaMs: Math.round(etaMs),
    providerCount: perProvider.size,
    sampleSize: usable.length,
  };
}
```

- [ ] **Step 6: Run ETA tests and watch pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useScanETA.test.ts
```

Expected: PASS — 4 tests.

- [ ] **Step 7: Full JS suite + typecheck**

Run:
```bash
cd <worktree>/web
npx vitest run
npm run typecheck
```

Expected: both PASS. Test count: 110 (106 + `formatMs` 4 from Task 6 + 4 `useScanETA` = 114 minus the 110 I mentioned — adjust to whatever vitest reports; the important thing is no regressions).

- [ ] **Step 8: Commit**

```bash
cd <worktree>
git add web/src/hooks/useScan.ts web/src/hooks/useScanETA.ts web/src/pages/Scan.tsx web/tests/unit/useScanETA.test.ts
git commit -m "feat(web): useScan explicit flag + useScanETA hook

useScan({ explicit: true }) appends ?snapshot=true to /api/scan so the
backend persists an auto-snapshot. Scan.tsx passes explicit: true on its
single call site (covers cold load + Rescan-now).
useScanETA fetches last 20 auto-snapshots, takes per-provider medians
scoped to enabled providers, sums them. Returns null when <3 samples."
```

---

## Task 8: Frontend — Scan page ETA display + Snapshots page visual treatment (TDD)

**Files:**
- Modify: `web/src/pages/Scan.tsx` (add ETA display next to scanning indicator)
- Modify: `web/src/pages/Snapshots.tsx` (dim auto rows, show duration + clock glyph)
- Modify or Create: `web/tests/unit/Snapshots.test.tsx`

- [ ] **Step 1: Inspect `Scan.tsx` to locate the scanning indicator**

Read `web/src/pages/Scan.tsx`. Find the text or element that renders "scanning…" (it may be inline in the toolbar next to the ↻ rescan button, or inside a loading indicator). Note the exact JSX.

The plan assumes the scanning indicator looks roughly like:

```tsx
{isFetching && <span className="text-text-muted text-[10px]">scanning…</span>}
```

If the real file has it structured differently (e.g., wrapped in a larger header component), locate the `scanning…` string and identify its parent element.

- [ ] **Step 2: Wire `useScanETA` into `Scan.tsx`**

At the top of `Scan.tsx`, add:

```tsx
import { useScanETA } from "@/hooks/useScanETA";
import { formatMs } from "@/lib/format";
```

Inside the `Scan` component body (near where `useScan(...)` is called), add:

```tsx
const eta = useScanETA();
```

Modify the scanning indicator to include the ETA suffix when available. For the hypothetical shape above:

```tsx
{isFetching && (
  <span className="text-text-muted text-[10px]">
    scanning…
    {eta.etaMs !== null && <> · ~{formatMs(eta.etaMs)}</>}
  </span>
)}
```

Adapt to the real file's JSX. The key is: when `eta.etaMs !== null`, append ` · ~<formatted ms>` to the existing indicator text. When null, render exactly the current scanning UI.

- [ ] **Step 3: Write the Snapshots page test**

Check whether `web/tests/unit/Snapshots.test.tsx` exists. If yes, append new tests. If not, create it:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import Snapshots from "@/pages/Snapshots";

vi.mock("@/api", () => ({
  apiFetch: vi.fn().mockResolvedValue([
    {
      name: "2026-04-24T12-00-00--manual.json",
      path: "/x/a.json",
      scanned_at: "2026-04-24T12:00:00Z",
      hostname: "h", platform: "darwin", note: null,
      total_bytes: 100, kind: "manual",
      duration_ms: 4821, entry_count: 10, per_provider: null,
    },
    {
      name: "2026-04-24T11-00-00--auto.json",
      path: "/x/b.json",
      scanned_at: "2026-04-24T11:00:00Z",
      hostname: "h", platform: "darwin", note: null,
      total_bytes: 50, kind: "auto",
      duration_ms: 2300, entry_count: 0, per_provider: null,
    },
  ]),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Snapshots page", () => {
  it("renders duration next to both auto and manual rows", async () => {
    render(<Snapshots />, { wrapper });
    // Manual row duration.
    expect(await screen.findByText("4.8s")).toBeInTheDocument();
    // Auto row duration.
    expect(await screen.findByText("2.3s")).toBeInTheDocument();
  });

  it("auto rows have the auto-kind badge", async () => {
    const { container } = render(<Snapshots />, { wrapper });
    // At least one element whose text contains 'auto'.
    await screen.findByText("4.8s"); // wait for data
    const autoBadges = Array.from(container.querySelectorAll("*")).filter(
      (el) => el.textContent?.trim() === "auto",
    );
    expect(autoBadges.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 4: Run the new test and watch it fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Snapshots.test.tsx
```

Expected: FAIL — duration strings not rendered yet.

- [ ] **Step 5: Update the Snapshots list row to show kind + duration**

Edit `web/src/pages/Snapshots.tsx`. Import `formatMs`:

```tsx
import { formatAbsTime, formatMs, humanBytes, timeAgo } from "@/lib/format";
```

Find the list-row render (inside `snapshots.map(...)`). The current row has two sub-rows: a top row with timeAgo + total_bytes, and a bottom row with formatAbsTime + note + delta.

Extend the top row to include the duration next to the total_bytes. Add the kind badge to the bottom row.

Target shape for the row:

```tsx
{snapshots.map((s, idx) => {
  const prev = snapshots[idx + 1];
  const delta = prev ? s.total_bytes - prev.total_bytes : null;
  const slot = slotOf(s.name);
  const flashing = flashName === s.name;
  const isAuto = s.kind === "auto";
  return (
    <button
      key={s.name}
      onClick={() => togglePick(s.name)}
      className={`block w-full text-left px-3 py-2.5 border-b border-border-subtle transition-colors ${
        flashing
          ? "bg-bg-safe-tint text-risk-safe"
          : slot
            ? "bg-bg-elev-2 text-text"
            : isAuto
              ? "text-text-muted hover:bg-bg-elev-1"
              : "text-text-dim hover:bg-bg-elev-1"
      }`}
      title={s.scanned_at}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <SlotBadge slot={slot} />
          <span className="font-medium truncate">{timeAgo(s.scanned_at)}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {typeof s.duration_ms === "number" && (
            <span className="text-text-muted text-[10px] tabular-nums">
              ⏱ {formatMs(s.duration_ms)}
            </span>
          )}
          <span className="tabular-nums text-text font-medium">
            {humanBytes(s.total_bytes)}
          </span>
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 mt-1">
        <div className="text-text-muted text-[10px] truncate">
          {formatAbsTime(s.scanned_at)}
          {s.kind && (
            <>
              {" · "}
              <span className="text-text-muted">{s.kind}</span>
            </>
          )}
          {s.note ? (
            <>
              {" · "}
              <span className="text-text-dim">{s.note}</span>
            </>
          ) : null}
        </div>
        {delta !== null && delta !== 0 ? (
          <span
            className={`text-[10px] tabular-nums shrink-0 ${
              delta > 0 ? "text-risk-danger" : "text-risk-safe"
            }`}
          >
            {delta > 0 ? "↑" : "↓"} {humanBytes(Math.abs(delta))}
          </span>
        ) : null}
      </div>
    </button>
  );
})}
```

Two changes:
1. The outer className gets a new `isAuto ? "text-text-muted" : "text-text-dim"` branch — auto rows render dimmer.
2. The top right-hand side shows a `⏱ 4.8s` span when `duration_ms` is present.
3. The bottom sub-row shows the kind string (`auto` or `manual`) between the abs-time and note.

- [ ] **Step 6: Run Snapshots tests + full suite**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Snapshots.test.tsx
npx vitest run
```

Expected: PASS on both. Typecheck:

```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/pages/Scan.tsx web/src/pages/Snapshots.tsx web/tests/unit/Snapshots.test.tsx
git commit -m "feat(web): Scan ETA display + Snapshots kind-aware list rows

Scan page's scanning indicator gets a static '~4s' suffix from useScanETA
when enough history exists. Snapshots list renders ⏱ duration_ms next to
the size, dims auto rows (text-text-muted vs text-text-dim for manual),
and shows the kind word between abs-time and note."
```

---

## Task 9: Build + visual verification

**Files:** none (read-only)

- [ ] **Step 1: Production build**

Run:
```bash
cd <worktree>/web
npm run build
```

Expected: clean build. Bundle delta sub-2 KB gzipped.

- [ ] **Step 2: Full frontend test sweep**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS. Roughly 115+ tests total.

- [ ] **Step 3: Full backend test sweep**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS. Roughly 195+ Python tests total.

- [ ] **Step 4: Dev-server manual check**

Run, in two terminals:

```bash
# Terminal A — backend
cd <worktree>
uv run diskdoctor serve --port 8731 --no-browser
```

```bash
# Terminal B — frontend
cd <worktree>/web
npm run dev
```

In the browser (port 5173):

1. **Scan page loads → an auto-snapshot is written.** Check that `~/.local/share/diskdoctor/snapshots/` (or wherever `default_snapshot_dir()` points) now has a `*--auto.json` file.
2. **Click "↻ rescan now".** Another `*--auto.json` file appears.
3. **Navigate away and back, change a filter** — no new auto-snapshot is written (filter changes re-fetch but don't pass `snapshot=true`).
4. **The scanning indicator shows an ETA** once there are ≥3 auto-snapshots with per-provider data. "scanning… · ~4s" or similar. (If fewer than 3, just "scanning…".)
5. **Snapshots page shows both kinds in one list.** Auto rows are dimmer; each row shows ⏱ duration; the kind word appears in the bottom sub-row.
6. **Diff two auto-snapshots** (or an auto vs a manual). Diff rows populate from per_provider totals — any two kinds should diff correctly.
7. **Retention: force a lot of scans** by reloading the Scan page ~55 times. Check that the snapshots directory has at most 50 `*--auto.json` files after the churn settles. (If the user doesn't want to wait, this is covered by the backend test.)

- [ ] **Step 5: Spot-check no regressions**

- Provider icons still render on Scan.
- Column picker still works.
- Disk-usage bar still refreshes after snapshot/scan/cleanup.
- Sidebar drag-resize still works.
- OS detection gate renders on non-supported UA.
- Create-manual-snapshot from the Snapshots page still works (the big-Report save flow).

- [ ] **Step 6: Final commit (only if touch-ups happened)**

If no changes beyond verification, skip. Otherwise stage + commit.

---

## Out of scope

- Live per-provider progress during a scan (SSE streaming). Deferred.
- User-configurable retention count (`AUTO_SNAPSHOT_RETENTION` is a module constant).
- "Convert auto to manual" action.
- Background/cron-driven auto-scans.
- Per-path timing inside a provider.
- ETA variance / confidence interval display.
- `duration_ms` as a sortable column on the Snapshots page.
- EWMA / ML-based ETA.

## Rollback

Nine commits, each self-contained. Reverting newest-first:

```bash
cd <worktree>
git log --oneline main..HEAD
# git revert each SHA in reverse order
```

No data migration required. `Report.from_json` handles v1 and v2; v1 files remain readable after any revert.
