# Scan telemetry — design

Date: 2026-04-24
Status: approved for implementation plan

## Goal

Four user-visible capabilities, delivered as one feature because they share data and storage:

1. **Record scan duration** — every scan captures total + per-provider timing.
2. **Persist every explicit scan** — the "Rescan now" button and cold page-loads write an auto-snapshot (lightweight, metadata-only) alongside the existing manual snapshots.
3. **ETA prediction** — before a scan fires, the UI shows a static `~4s` estimate derived from the median of recent auto-snapshot durations, scoped to the currently-enabled providers.
4. **Unified snapshot listing** — the Snapshots page renders auto and manual snapshots in one time-ordered list, visually distinguished.

## Key conceptual move

Today the codebase has two words for the same thing: a **scan** is an in-memory `Report`; a **snapshot** is a `Report` that was saved to disk. This spec collapses those into one model: **every scan produces a snapshot**, and the snapshot has a `kind` discriminator. `kind: "auto"` snapshots are small (metadata only); `kind: "manual"` snapshots are what we save today (full entries). One storage format, one listing, one diff algorithm.

## Schema

### Snapshot JSON (on-disk, schema v2)

```json
{
  "schema_version": 2,
  "kind": "auto",
  "scanned_at": "2026-04-24T10:15:03Z",
  "started_at": "2026-04-24T10:14:58Z",
  "duration_ms": 4821,
  "hostname": "...",
  "platform": "darwin",
  "total_bytes": 53800000000,
  "entry_count": 43,
  "per_provider": [
    { "name": "ollama",          "bytes": 29800000000, "entries": 7, "duration_ms": 120  },
    { "name": "huggingface-hub", "bytes":  5900000000, "entries": 3, "duration_ms": 2900 }
  ],
  "note": null,
  "entries": null,
  "skipped_paths": []
}
```

- `kind` — `"auto"` or `"manual"`.
- `started_at`, `scanned_at`, `duration_ms` — redundantly stored so readers don't re-derive from timestamps (floating-point noise).
- `duration_ms` uses `time.monotonic()` deltas, not wall-clock — immune to NTP adjustments mid-scan.
- `per_provider[].duration_ms` — the granularity ETA math needs.
- `total_bytes` and `entry_count` — snapshot-level summaries, exposed so the list view doesn't re-derive them from `entries`.
- `entries: null` for `kind: "auto"` — omits the per-entry dump (which is 95%+ of a manual snapshot's bytes). `entries: [...]` for `kind: "manual"` — unchanged.
- `skipped_paths` — retained (some providers report paths they couldn't stat).

### Filename convention

- Auto: `2026-04-24T10-15-03--auto.json`
- Manual: `2026-04-24T10-15-03--manual.json`
- Pre-feature (v1): `2026-04-24T10-15-03.json` — no suffix. Treated as manual on read; never culled by the retention prune.

The `--<kind>` suffix lets retention glob `*--auto.json` without reading file contents.

## Backend changes

### `src/diskdoctor/types.py`

Add an enum and a nested dataclass, then extend `Report`:

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


@dataclass
class Report:
    entries: list[Entry]
    scanned_at: datetime
    hostname: str
    platform: str
    note: str | None = None
    skipped_paths: list[str] = field(default_factory=list)
    # NEW — all default to values that preserve pre-feature semantics for
    # existing callers (tests, CLI) that construct Report by hand.
    kind: SnapshotKind = SnapshotKind.MANUAL
    started_at: datetime | None = None
    duration_ms: int | None = None
    per_provider: list[ProviderTiming] = field(default_factory=list)
```

Bump `SNAPSHOT_SCHEMA_VERSION = 2`.

### `Report.to_json` / `Report.from_json`

`to_json`:
- Emit `schema_version: 2`, `kind`, `started_at` (ISO or null), `duration_ms`, `per_provider`.
- Emit `total_bytes` (computed via `self.total_bytes()`) and `entry_count` as top-level convenience.
- When `kind == AUTO`, emit `"entries": null` and skip the per-entry serialization.
- When `kind == MANUAL`, emit `"entries": [...]` unchanged from v1.

`from_json`:
- Read `schema_version`. If `1` (pre-feature), set `kind = MANUAL`, leave new fields at defaults (None / empty list). File still parses; ETA math ignores it.
- If `2`, parse all new fields.
- If `3+` (future), log a warning and best-effort parse (unknown keys ignored — consistent with the existing policy).
- Backward-compat: `entries` → empty list when `null`, so downstream code that iterates `entries` keeps working even on auto-snapshots.

### `src/diskdoctor/discovery.py`

Replace the current plain loop with a timed version:

```python
import time
from datetime import UTC, datetime

from diskdoctor.types import ProviderTiming, Report, ScanFilters, SnapshotKind


def scan(providers, filters, now):
    started_at = datetime.now(UTC)
    entries = []
    per_provider = []
    for p in providers:
        if not p.available():
            continue
        t0 = time.monotonic()
        provider_entries = p.discover()
        dt_ms = int((time.monotonic() - t0) * 1000)
        entries.extend(provider_entries)
        per_provider.append(ProviderTiming(
            name=p.name,
            bytes=sum(e.size_bytes for e in provider_entries),
            entries=len(provider_entries),
            duration_ms=dt_ms,
        ))
    scanned_at = datetime.now(UTC)
    duration_ms = int((scanned_at - started_at).total_seconds() * 1000)

    entries.sort(key=lambda e: e.size_bytes, reverse=True)
    report = Report(
        entries=entries,
        scanned_at=scanned_at,
        hostname=socket.gethostname(),
        platform=_platform(),
        kind=SnapshotKind.MANUAL,           # caller overrides to AUTO when writing auto-snapshot
        started_at=started_at,
        duration_ms=duration_ms,
        per_provider=per_provider,
    )
    if filters.min_size_bytes or filters.risks is not None or filters.providers is not None:
        report = report.filter(...)
    return report
```

The `kind` default is `MANUAL`; the caller overrides to `AUTO` when it's about to write an auto-snapshot. (`Report.filter` returns a new Report with the same `kind` — see `.filter` pass-through below.)

`Report.filter` needs to forward the new fields when cloning:

```python
return Report(
    entries=[...],
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

### `src/diskdoctor/history.py`

Two new helpers and a retention prune:

```python
AUTO_SNAPSHOT_RETENTION = 50

def write_snapshot(report: Report, directory: Path) -> Path:
    """Write a snapshot atomically. Filename includes --<kind>.json suffix."""
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


def prune_auto_snapshots(directory: Path, keep: int = AUTO_SNAPSHOT_RETENTION) -> list[Path]:
    """Delete oldest auto-snapshots beyond `keep`. Manual snapshots untouched.
    Returns list of deleted paths.
    """
    if not directory.exists():
        return []
    autos = sorted(directory.glob("*--auto.json"), reverse=True)
    victims = autos[keep:]
    for p in victims:
        with contextlib.suppress(FileNotFoundError, PermissionError):
            p.unlink()
    return victims
```

Callers:
- The scan endpoint with `?snapshot=true` calls `write_snapshot(report_with_kind_auto)` then `prune_auto_snapshots(...)`.
- Manual snapshot creation calls `write_snapshot(report_with_kind_manual)` — no prune (manuals are forever).

### API: `/api/scan` accepts `?snapshot=true`

```python
@router.get("/scan")
def scan(
    request: Request,
    min_size: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    snapshot: bool = Query(default=False),
) -> JSONResponse:
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, filters, datetime.now(UTC))
    if snapshot:
        auto_report = dataclasses.replace(report, kind=SnapshotKind.AUTO)
        history.write_snapshot(auto_report, history.default_snapshot_dir())
        history.prune_auto_snapshots(history.default_snapshot_dir())
    return JSONResponse(content=_report_to_dict(report))
```

The snapshot write is synchronous — it's a small JSON file, single-digit ms even on slow disks, and keeps semantics simple (response body and disk state are consistent at return time). If profiling later shows this is a bottleneck, we can fire-and-forget via a thread. Deferred.

### API: `/api/snapshots` gets query params

```python
@router.get("/snapshots")
def list_snapshots(
    limit: int | None = Query(default=None),
    kind: Literal["auto", "manual", "all"] = Query(default="all"),
) -> list[SnapshotMeta]:
    ...
```

- Default (no params): return all, newest first — preserves current behavior.
- `?kind=auto` / `?kind=manual` — filter by kind.
- `?limit=N` — cap response count.

`SnapshotMeta` Pydantic model gains optional fields:

```python
class SnapshotMeta(BaseModel):
    name: str
    path: str
    scanned_at: str
    hostname: str
    platform: str
    note: str | None
    total_bytes: int
    # NEW — optional so v1 files serve without them
    kind: Literal["auto", "manual"] = "manual"  # v1 files → default manual
    duration_ms: int | None = None
    entry_count: int | None = None
    per_provider: list[dict] | None = None      # raw dicts; no pydantic sub-model needed
```

### `history.diff` handles both kinds

Current diff sums `e.size_bytes` across entries to compute per-provider totals. Auto-snapshots don't have entries but do have `per_provider` totals directly. Update:

```python
def _totals_by_provider(report: Report) -> dict[str, int]:
    """Prefer per_provider totals (v2) when present; fall back to summing
    entries (v1 or manual v2). Returns a dict of provider-name → bytes.
    """
    if report.per_provider:
        return {pt.name: pt.bytes for pt in report.per_provider}
    return {p: sum(e.size_bytes for e in es) for p, es in report.by_provider().items()}
```

Makes all four combinations work: auto/auto, auto/manual, manual/auto, manual/manual (and old v1 files without timing data).

## Frontend changes

### `useScan` gains an explicit flag

```ts
interface UseScanOptions {
  explicit?: boolean;  // true = this refetch should persist as an auto-snapshot
}

export function useScan(options: UseScanOptions = {}): ...
```

- Internal: when `explicit: true`, the fetch URL is `/api/scan?snapshot=true`. Otherwise plain `/api/scan`.
- `Scan.tsx`'s cold-load: `useScan({ explicit: true })`.
- `Scan.tsx`'s "Rescan now" button: calls `refetch()`, which under TanStack Query re-uses the hook's query key. Simplest: the query key itself includes `snapshot`, and the "Rescan now" handler invalidates the non-explicit query then triggers an explicit one. Implementation detail for the plan.

### New hook: `useScanETA`

```ts
export function useScanETA(): {
  etaMs: number | null;
  providerCount: number;   // active providers factored into the estimate
  sampleSize: number;      // how many snapshots the estimate is drawn from
}
```

- Fetches `/api/snapshots?kind=auto&limit=20`.
- Filters to rows with `duration_ms !== null` and `per_provider.length > 0`.
- Reads `useSelectedProviders` for the currently-enabled set.
- For each enabled provider: gathers all its `per_provider[i].duration_ms` across fetched snapshots, computes the median.
- Returns `etaMs = sum of medians`, `providerCount = enabled providers that had data`, `sampleSize = snapshots used`.
- Returns `{ etaMs: null, ... }` if `sampleSize < 3` (not enough history to predict reliably).

Median implementation: sort, pick middle (or average of two middles for even n). Vanilla JS, ~10 lines.

### Scan page

The scanning indicator (current `scanning…` text / spinner) gets an ETA suffix when available:

```tsx
{isFetching && (
  <span className="text-text-muted text-[10px]">
    scanning…
    {eta.etaMs !== null && <> · ~{formatMs(eta.etaMs)}</>}
  </span>
)}
```

`formatMs` helper — sub-second → `"600ms"`, ≥1s → `"4s"`, ≥60s → `"1m 12s"`. Lives alongside `humanBytes` in `lib/format.ts`.

No mid-scan animation or countdown. The indicator disappears when the scan completes.

### Snapshots page

List row extended with two new visual elements:

- **Clock icon + duration** after the `total_bytes`. Example: `53.8G · ⏱ 4.8s`. Uses the existing Unicode clock glyph from the provider-icon set.
- **Dimmer text color for auto rows** (`text-text-dim` instead of `text-text`). Manual rows keep today's look.
- Sort order: newest-first by `scanned_at`, merged (no separate sections).

Row shape in pseudocode:

```tsx
<div className={row.kind === "auto" ? "text-text-dim" : "text-text"}>
  <span>{formatDate(row.scanned_at)}</span>
  <span>{humanBytes(row.total_bytes)}</span>
  {row.duration_ms !== null && (
    <span className="text-text-muted">⏱ {formatMs(row.duration_ms)}</span>
  )}
  <span className="text-text-muted text-[9px]">{row.kind}</span>
</div>
```

### Diff page

No UI changes. The backend's `_totals_by_provider` update means auto-against-auto and auto-against-manual diffs work automatically — the frontend doesn't know or care about `kind` when rendering the diff table.

## Accessibility

- Clock icon on auto rows: `aria-hidden="true"` (decorative, row's scanned_at + duration already announce the same info).
- ETA text in scanning indicator: plain text, no extra ARIA needed. Screen readers read "scanning, about 4 seconds" which is useful.
- No focus traps introduced. No new keyboard shortcuts.

## Edge cases

- **Cold start, zero history** — `useScanETA` returns `etaMs: null`, UI shows just `scanning…` without an estimate.
- **User disables all providers** — scan runs, produces an empty auto-snapshot with `total_bytes: 0`, `entry_count: 0`, empty `per_provider`. Written and pruned as normal. Subsequent ETA math returns 0, which renders `scanning… · ~0ms` — weird but self-resolving (no providers to scan = no time spent).
- **User enables a provider for the first time** — ETA's `per_provider` medians excluded that provider (no historical data for it). The estimate understates duration. After one scan with the new provider, the next ETA includes it. Acceptable.
- **Schema v1 snapshot encountered during listing** — served with `kind: "manual"`, `duration_ms: null`. Displays on Snapshots page with no clock-icon suffix. Diff still works via the fall-through in `_totals_by_provider`.
- **Scan errors mid-loop** — currently, if a provider's `discover()` raises, the whole scan raises. That stays the same; timing is captured only for providers that completed. Not a regression, not a new concern for this feature.
- **Two concurrent `?snapshot=true` requests** — both write files. Filename timestamp is per-second granularity, so collisions are possible (same second → same name). Mitigation: if filename exists on write, append a 3-digit disambiguator (`...--auto.001.json`). Low probability in single-user local tool; still worth the safety net.
- **Disk-full during auto-snapshot write** — the atomic-rename helper raises. `/api/scan` catches, logs a warning, still returns the scan response. The user doesn't get the snapshot but their scan display works. Existing exception handling already covers this in the atomic-write helper; just make sure the scan-endpoint doesn't propagate write failures back to the client.

## Testing

### Backend

- `tests/test_types.py` — `Report` with new fields round-trips; auto shape with `entries: null` round-trips to empty `entries: []`. v1-shaped JSON parses cleanly with `kind = MANUAL` and timing fields as None/empty.
- `tests/test_discovery.py` — `scan()` returns a Report with non-None `started_at`, `duration_ms`, and a `per_provider` row per available provider. Durations are non-negative integers. Sum of per_provider durations ≤ overall duration (overhead is small but non-zero).
- `tests/test_history.py` — `write_snapshot(Report(kind=AUTO))` produces a file with `--auto.json` suffix containing `entries: null`. `write_snapshot(Report(kind=MANUAL))` produces `--manual.json` with full entries.
- `tests/test_history.py` — `prune_auto_snapshots(dir, keep=3)` with 5 auto files: keeps newest 3, deletes oldest 2. Manual files in the same dir are untouched.
- `tests/test_history.py` — `diff()` between auto/auto, auto/manual, manual/auto, manual/manual all yield the same result when total bytes match.
- `tests/web/test_routes_scan.py` — `GET /api/scan?snapshot=true` writes an auto-snapshot; `GET /api/scan` does not. Response shape is unchanged between the two.
- `tests/web/test_routes_history.py` — `GET /api/snapshots?kind=auto` filters to auto only; `?kind=manual` to manual only; default returns all. `?limit=N` caps count.

### Frontend

- `web/tests/unit/format.test.ts` — `formatMs` handles sub-second, second, minute-plus.
- `web/tests/unit/useScanETA.test.ts` — with 5 fake auto-snapshots and 4 enabled providers, returns expected median-sum. Respects disabled providers (excludes their durations from the sum). Returns `null` with <3 samples. Returns `null` with no enabled-provider history.
- `web/tests/unit/useScan.test.ts` — `useScan({ explicit: true })` URL contains `snapshot=true`; default `useScan()` does not.
- `web/tests/unit/Scan.test.tsx` (extend if present; skip otherwise) — scanning indicator shows `~4s` when `etaMs` is non-null.
- `web/tests/unit/Snapshots.test.tsx` (new or extend) — auto rows have clock glyph and dim class; manual rows don't; `duration_ms` renders via `formatMs`.

### No new e2e tests

Standard for this codebase. Unit coverage is adequate for the scope.

## Non-goals

- Live per-provider progress during a running scan (SSE streaming). Deferred; separate brainstorm if you want it later.
- User-configurable retention count (`AUTO_SNAPSHOT_RETENTION` is a module constant).
- Admin UI for deleting snapshots. Snapshots are manually deletable from the filesystem today; that stays.
- "Convert an auto to a manual" action. User creates a new manual via the existing save flow.
- Background/cron-driven auto-scans. Auto-snapshots fire only on user-driven events.
- Per-path timing inside a provider.
- ETA variance / confidence interval display.
- Exposing `duration_ms` as a sortable column on the Snapshots page.
- EWMA / ML-based ETA.

## Rollout impact

- **Starting test count**: 106 JS + 179 Python = 285.
- **Added**: ~10 JS, ~15 Python → ~310 total after the feature lands.
- **Bundle delta**: sub-2 KB gzipped (one new hook, small Snapshots/Scan page tweaks, `formatMs` helper).
- **Storage**: 50 retained auto-snapshots × ~800 bytes each ≈ 40 KB worst-case for auto-snapshot disk footprint. Manual snapshots unchanged.
- **API response change**: `/api/snapshots` rows gain optional fields; old clients tolerate them. `/api/scan` accepts one new optional query param; no response change.

## Open questions resolved during brainstorming

- **Persistence model** (Q1): unified "every scan is a snapshot, discriminated by `kind`." One storage format.
- **Trigger policy** (Q2 → A): auto-snapshot writes only on explicit Rescan (cold load + Rescan-now button). No writes on filter/nav re-fetches.
- **Timing granularity** (Q3 → B): per-provider durations + total.
- **ETA algorithm** (Q4a → A): median of last ~20 auto-snapshots, summed over currently-enabled providers.
- **ETA display** (Q4b → X): static pre-estimate shown next to the scanning indicator. No live per-provider updates.
- **Retention** (Q5a → A): keep last 50 auto-snapshots; manual unbounded.
- **Snapshots page** (Q5b → P): unified list, dim styling + clock glyph for auto rows.
