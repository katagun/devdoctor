# One Scan at a Time, No Rescan After Cleanup: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identical scans never run concurrently, and a finished cleanup updates the Disk page without starting a full rescan.

**Architecture:**
- A thread-safe `ScanCoalescer` lets concurrent `GET /api/scan` requests with equal `ScanFilters` share one scan.
- On the client, a finished cleanup records a *removal* (ids + paths + time) in the query client and applies it to every cached scan.
- `useScan` re-applies any removal newer than a scan's `started_at`, so a scan that was already running cannot bring deleted rows back.
- The scan query waits for the provider list when a provider filter depends on it.

**Tech Stack:** Python 3.12, FastAPI/Starlette (sync route on worker threads), pytest; React 19, TanStack Query v5, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-scan-dedupe-design.md`

## Global Constraints

- Nothing that deletes changes: `POST /api/clean/jobs` and its re-check never go through the coalescer.
- A request that joins a running scan returns that scan's report and writes nothing itself; the storage writes (dashboard summary, auto-snapshot) happen once, in the request that ran the scan.
- The browser and the backend share a clock (the server only answers `127.0.0.1`), so `Date.now()` and a report's `started_at` are comparable.
- No abort signal on scan requests (spec, Non-goals).
- Tests: `.venv/bin/python -m pytest -q -p no:cacheprovider`, `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`, `.venv/bin/mypy`. Web: in `web/`, `bun run lint`, `bun run typecheck`, `bun run test`, `bun run build`, `bun run test:e2e`.
  - Web tooling needs node 24: put `~/.nvm/versions/node/v24.19.0/bin` first on PATH. If commands containing `PATH=` are rejected, use a small wrapper script that prepends it.
  - `bun run test:e2e` rebuilds the SPA and overwrites the tracked placeholder `src/devdoctor/web/_static/dist/index.html`. Restore it afterwards with `git checkout -- src/devdoctor/web/_static/dist/index.html`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The pre-commit hook may reformat and abort; re-add and commit again.

---

### Task 1: `ScanCoalescer`

**Files:**
- Create: `src/devdoctor/web/scan_coalescer.py`
- Test: `tests/web/test_scan_coalescer.py`

**Interfaces:**
- Produces: `ScanCoalescer[T]` with `run(key: Hashable, scan: Callable[[], T]) -> T`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_scan_coalescer.py
"""Two identical scans at once share the sizer's workers and slow each other about 5x."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from devdoctor.web.scan_coalescer import ScanCoalescer


def _held(started: threading.Event, release: threading.Event, calls: list[int], value):
    def scan():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return value

    return scan


def test_concurrent_requests_for_one_key_share_one_scan():
    coalescer: ScanCoalescer[object] = ScanCoalescer()
    started, release, calls, report = threading.Event(), threading.Event(), [], object()
    scan = _held(started, release, calls, report)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coalescer.run, "k", scan)
        assert started.wait(5)
        second = pool.submit(coalescer.run, "k", scan)
        # The second request waits for the running scan instead of finishing on its own.
        with pytest.raises(TimeoutError):
            second.result(timeout=0.3)
        release.set()
        assert first.result(5) is report
        assert second.result(5) is report
    assert calls == [1]


def test_a_scan_of_other_filters_does_not_wait():
    coalescer: ScanCoalescer[str] = ScanCoalescer()
    started, release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(1) as pool:
        held = pool.submit(coalescer.run, "a", _held(started, release, [], "a"))
        assert started.wait(5)
        assert coalescer.run("b", lambda: "b") == "b"
        release.set()
        assert held.result(5) == "a"


def test_a_failed_scan_fails_every_waiter_and_the_next_request_scans_again():
    coalescer: ScanCoalescer[str] = ScanCoalescer()
    started, release = threading.Event(), threading.Event()

    def failing():
        started.set()
        assert release.wait(5)
        raise OSError("the volume went away")

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coalescer.run, "k", failing)
        assert started.wait(5)
        second = pool.submit(coalescer.run, "k", failing)
        with pytest.raises(TimeoutError):
            second.result(timeout=0.3)
        release.set()
        for request in (first, second):
            with pytest.raises(OSError, match="the volume went away"):
                request.result(5)
    assert coalescer.run("k", lambda: "fresh") == "fresh"


def test_a_request_after_the_scan_finished_starts_a_new_one():
    coalescer: ScanCoalescer[int] = ScanCoalescer()
    calls: list[int] = []

    def scan() -> int:
        calls.append(1)
        return len(calls)

    assert coalescer.run("k", scan) == 1
    assert coalescer.run("k", scan) == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/web/test_scan_coalescer.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'devdoctor.web.scan_coalescer'`.

- [ ] **Step 3: Implement**

```python
# src/devdoctor/web/scan_coalescer.py
"""One scan per filter set at a time, shared by every request that asks for it."""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from concurrent.futures import Future


class ScanCoalescer[T]:
    """Runs at most one scan per key at a time.

    A request for a key whose scan is running waits for that scan and gets its
    result instead of starting another: two scans of the same filters share the
    sizer's walk workers and slow each other about 5x. Requests arrive on worker
    threads, hence the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[Hashable, Future[T]] = {}

    def run(self, key: Hashable, scan: Callable[[], T]) -> T:
        with self._lock:
            running = self._running.get(key)
            leader = running is None
            if running is None:
                running = Future()
                self._running[key] = running
        if not leader:
            return running.result()
        try:
            result = scan()
        except BaseException as exc:
            running.set_exception(exc)
            raise
        finally:
            with self._lock:
                del self._running[key]
        running.set_result(result)
        return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/web/test_scan_coalescer.py -q -p no:cacheprovider`, then `.venv/bin/ruff check src tests && .venv/bin/mypy`
Expected: 4 passed; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/web/scan_coalescer.py tests/web/test_scan_coalescer.py
git commit -m "feat(web): a coalescer that runs one scan per filter set at a time"
```

---

### Task 2: `GET /api/scan` shares a running scan

**Files:**
- Modify: `src/devdoctor/web/app.py` (next to `app.state.scan_progress = ScanProgressHub()`)
- Modify: `src/devdoctor/web/routes_scan.py` (the `scan` route)
- Test: `tests/web/test_routes_scan.py`

**Interfaces:**
- Consumes: `ScanCoalescer` (Task 1).
- Produces: `app.state.scan_coalescer: ScanCoalescer[Report]`.

- [ ] **Step 1: Write the failing test** (append to `tests/web/test_routes_scan.py`; add `import threading` to the imports)

```python
async def test_concurrent_scans_of_the_same_filters_share_one_scan(tmp_path, monkeypatch):
    """Two identical full scans used to run at once and slow each other about 5x."""
    from devdoctor.web import routes_scan

    sock, port = _bind_loopback_socket()
    app = _app_for_port(tmp_path, monkeypatch, port)
    real_scan = routes_scan.discovery.scan
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def gated_scan(*args, **kwargs):
        calls.append(1)
        entered.set()
        release.wait(10)
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(routes_scan.discovery, "scan", gated_scan)
    storage_type = type(app.state.storage)
    real_write = storage_type.write_disk_dashboard_summary
    writes: list[object] = []

    def counting_write(self, report):
        writes.append(report)
        return real_write(self, report)

    monkeypatch.setattr(storage_type, "write_disk_dashboard_summary", counting_write)

    with run_server(app, sock):
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as c:
            first = asyncio.create_task(c.get("/api/scan", timeout=15))
            second = None
            try:
                assert await asyncio.to_thread(entered.wait, 10)
                second = asyncio.create_task(c.get("/api/scan", timeout=15))
                await asyncio.sleep(0.3)  # the second request reaches the server and joins
            finally:
                release.set()
                one = await first
                two = await second if second is not None else None

    assert one.status_code == 200
    assert two is not None and two.status_code == 200
    assert one.json()["entries"] == two.json()["entries"]
    assert len(calls) == 1
    assert len(writes) == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/web/test_routes_scan.py -q -p no:cacheprovider -k share_one_scan`
Expected: FAIL: `assert len(calls) == 1` sees 2.

- [ ] **Step 3: Implement**

In `src/devdoctor/web/app.py`, import `from devdoctor.web.scan_coalescer import ScanCoalescer` and add after the progress hub:

```python
    # One scan per filter set at a time: a request for filters already being scanned
    # shares that scan, since two at once slow each other about 5x.
    app.state.scan_coalescer = ScanCoalescer()
```

In `src/devdoctor/web/routes_scan.py`, replace the body of `scan` after building `filters` with:

```python
    storage: StorageBackend = request.app.state.storage

    def scan_and_store() -> Report:
        providers_list = registry.load_providers(request.app.state.shell)
        report = discovery.scan(
            providers_list,
            filters,
            datetime.now(UTC),
            on_progress=request.app.state.scan_progress.observer(),
        )
        # Only an unfiltered scan may be stored: a filtered report's totals cover part of
        # the disk, and would read as a drop in history (#103).
        if filters.is_unfiltered:
            try:
                storage.write_disk_dashboard_summary(report)
            except OSError as exc:
                logger.warning("scan: failed to write dashboard summary: %s", exc)
        if (
            snapshot
            and filters.is_unfiltered
            and _should_write_auto_snapshot(storage, snapshot_min_interval_ms)
        ):
            auto_report = dataclasses.replace(report, kind=SnapshotKind.AUTO)
            try:
                storage.write_disk_snapshot(auto_report)
                storage.prune_auto_disk_snapshots(keep=history.AUTO_SNAPSHOT_RETENTION)
            except OSError as exc:
                # Disk full / permission denied / whatever — don't fail the
                # scan response because the auto-snapshot write choked. Client
                # still gets the scan; next scan will try again.
                logger.warning("scan: auto-snapshot write failed: %s", exc)
        return report

    # A request for filters whose scan is already running waits for it and returns
    # its report: the scan, and its storage writes, happen once.
    report = request.app.state.scan_coalescer.run(filters, scan_and_store)
    return JSONResponse(content=_report_to_dict(report))
```

(The old top-level `providers_list = ...`, `report = discovery.scan(...)`, `storage = ...` and the two write blocks move into `scan_and_store` unchanged.)

- [ ] **Step 4: Run the route tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/web/test_routes_scan.py -q -p no:cacheprovider`, then the full suite, ruff and mypy.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/web/app.py src/devdoctor/web/routes_scan.py tests/web/test_routes_scan.py
git commit -m "fix(web): requests for the same scan share it instead of running it twice"
```

---

### Task 3: Removals and `applyRemovals`

**Files:**
- Modify: `web/src/lib/scanRows.ts`
- Create: `web/src/lib/cleanupRemovals.ts`
- Test: `web/tests/unit/scanRows.test.ts`, `web/tests/unit/cleanupRemovals.test.ts`

**Interfaces:**
- Produces:
  - `web/src/lib/scanRows.ts`:
    - `interface Removal { ids: string[]; paths: string[]; at: number }`
    - `interface ScanResult { rows: CacheTableRow[]; totalBytes: number; scannedAt: string; startedAt: string | null; coverage: ScanCoverage | null }`
    - `applyRemovals(result: ScanResult, removals: readonly Removal[]): ScanResult`
  - `web/src/lib/cleanupRemovals.ts`:
    - `removalFrom(results: CleanupResult[], entries: CacheTableRow[], at: number): Removal | null`
    - `recordRemoval(client: QueryClient, removal: Removal): void`
    - `removalsSince(client: QueryClient, startedAt: string | null): Removal[]`

- [ ] **Step 1: Write the failing tests**

Append to `web/tests/unit/scanRows.test.ts` (extend the import with `applyRemovals, type ScanResult`):

```ts
function result(rows: CacheTableRow[]): ScanResult {
  return {
    rows,
    totalBytes: rows.reduce((sum, r) => sum + (r.risk === "dangerous" ? 0 : (r.reclaimable_bytes ?? 0)), 0),
    scannedAt: "2026-09-25T10:00:00+00:00",
    startedAt: "2026-09-25T09:58:00+00:00",
    coverage: { usedBytes: 10_000, classifiedBytes: 4_000, ratio: 0.4 },
  };
}

describe("applyRemovals", () => {
  it("drops the removed rows and what they held from the totals", () => {
    const before = result([row("a", 1_000), row("b", 500)]);
    const after = applyRemovals(before, [{ ids: ["a"], paths: [], at: 1 }]);
    expect(after.rows.map((r) => r.id)).toEqual(["b"]);
    expect(after.totalBytes).toBe(500);
    expect(after.coverage).toEqual({ usedBytes: 9_000, classifiedBytes: 3_000, ratio: 3_000 / 9_000 });
  });

  it("drops rows at or under a removed path, but not a sibling that shares a prefix", () => {
    const worktree = { ...row("wt", 800), path: "/code/app/.worktrees/feat" };
    const inside = { ...row("nm", 300), path: "/code/app/.worktrees/feat/node_modules" };
    const sibling = { ...row("other", 200), path: "/code/app/.worktrees/feature-two" };
    const after = applyRemovals(result([worktree, inside, sibling]), [
      { ids: [], paths: ["/code/app/.worktrees/feat"], at: 1 },
    ]);
    expect(after.rows.map((r) => r.id)).toEqual(["other"]);
  });

  it("never counts a dangerous row toward the reclaimable total it takes back", () => {
    const risky = row("d", 700, 700, "dangerous");
    const before = result([risky, row("s", 100)]);
    expect(applyRemovals(before, [{ ids: ["d"], paths: [], at: 1 }]).totalBytes).toBe(100);
  });

  it("returns the scan unchanged when nothing matches", () => {
    const before = result([row("a", 1)]);
    expect(applyRemovals(before, [{ ids: ["zzz"], paths: ["/nowhere"], at: 1 }])).toBe(before);
  });
});
```

Create `web/tests/unit/cleanupRemovals.test.ts`:

```ts
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CacheTableRow } from "@/components/CacheTable";
import { recordRemoval, removalFrom, removalsSince } from "@/lib/cleanupRemovals";

function row(id: string, path: string): CacheTableRow {
  return {
    id,
    provider: "p",
    label: id,
    path,
    size_bytes: 1,
    footprint_bytes: 1,
    reclaimable_bytes: 1,
    shared_bytes: 0,
    risk: "safe",
    mtime: null,
    recipeHint: "",
    owner: null,
    group: null,
    perms: null,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("removalFrom", () => {
  it("keeps only what the cleanup actually removed, with the paths it knows", () => {
    const removal = removalFrom(
      [
        { entry_id: "a", status: "ok", freed_bytes: 1 },
        { entry_id: "b", status: "error", freed_bytes: 0 },
        { entry_id: "c", status: "ok", freed_bytes: 1 },
      ],
      [row("a", "/x/a"), row("b", "/x/b"), row("c", "—")],
      42,
    );
    expect(removal).toEqual({ ids: ["a", "c"], paths: ["/x/a"], at: 42 });
  });

  it("is nothing when nothing was removed", () => {
    expect(removalFrom([{ entry_id: "a", status: "skipped", freed_bytes: 0 }], [], 1)).toBeNull();
  });
});

describe("removals in the query client", () => {
  it("returns the removals newer than a scan's start, or all when the start is unknown", () => {
    const client = new QueryClient();
    recordRemoval(client, { ids: ["old"], paths: [], at: Date.parse("2026-09-25T09:00:00Z") });
    recordRemoval(client, { ids: ["new"], paths: [], at: Date.parse("2026-09-25T11:00:00Z") });
    expect(removalsSince(client, "2026-09-25T10:00:00+00:00").map((r) => r.ids[0])).toEqual(["new"]);
    expect(removalsSince(client, null)).toHaveLength(2);
  });

  it("outlives the query client's garbage collection", () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    recordRemoval(client, { ids: ["a"], paths: [], at: 1 });
    vi.advanceTimersByTime(60 * 60 * 1000);
    expect(removalsSince(client, null)).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `web/`): `bunx vitest run tests/unit/scanRows.test.ts tests/unit/cleanupRemovals.test.ts`
Expected: FAIL: `applyRemovals` is not exported; `@/lib/cleanupRemovals` cannot be resolved.

- [ ] **Step 3: Implement**

Append to `web/src/lib/scanRows.ts`:

```ts
/** What a cleanup removed: rows with these ids, and anything at or under these paths. */
export interface Removal {
  ids: string[];
  paths: string[];
  /** When the cleanup's result arrived, in ms since the epoch. */
  at: number;
}

/** A scan as the Disk page and the Dashboard hold it. */
export interface ScanResult {
  rows: CacheTableRow[];
  totalBytes: number;
  scannedAt: string;
  /** The server's clock when the scan began; null from a server that predates it. */
  startedAt: string | null;
  coverage: ScanCoverage | null;
}

function removedBy(row: CacheTableRow, removals: readonly Removal[]): boolean {
  return removals.some(
    (removal) =>
      removal.ids.includes(row.id) ||
      removal.paths.some((path) => row.path === path || row.path.startsWith(`${path}/`)),
  );
}

/**
 * The scan without the rows these cleanups removed, its totals reduced by what
 * those rows held. Rows under a removed path go too: a worktree's contents are
 * deleted with it (spec §6.4).
 */
export function applyRemovals(result: ScanResult, removals: readonly Removal[]): ScanResult {
  if (removals.length === 0) return result;
  const rows: CacheTableRow[] = [];
  let reclaimable = 0;
  let footprint = 0;
  for (const row of result.rows) {
    if (!removedBy(row, removals)) {
      rows.push(row);
      continue;
    }
    if (row.risk !== "dangerous") reclaimable += row.reclaimable_bytes ?? 0;
    footprint += row.footprint_bytes ?? 0;
  }
  if (rows.length === result.rows.length) return result;
  let coverage = result.coverage;
  if (coverage) {
    const usedBytes = Math.max(0, coverage.usedBytes - footprint);
    const classifiedBytes = Math.max(0, coverage.classifiedBytes - footprint);
    coverage = { usedBytes, classifiedBytes, ratio: usedBytes > 0 ? classifiedBytes / usedBytes : null };
  }
  return { ...result, rows, totalBytes: Math.max(0, result.totalBytes - reclaimable), coverage };
}
```

Create `web/src/lib/cleanupRemovals.ts`:

```ts
import type { QueryClient } from "@tanstack/react-query";
import type { CacheTableRow } from "@/components/CacheTable";
import type { CleanupResult } from "@/components/CleanupWizard/CleanupWizardState";
import type { Removal } from "@/lib/scanRows";

const REMOVALS_KEY = ["cleanup-removals"] as const;

/** What a cleanup removed, or null when it removed nothing. */
export function removalFrom(
  results: CleanupResult[],
  entries: CacheTableRow[],
  at: number,
): Removal | null {
  const ids = results.filter((result) => result.status === "ok").map((result) => result.entry_id);
  if (ids.length === 0) return null;
  const removed = new Set(ids);
  const paths = entries
    .filter((entry) => removed.has(entry.id) && entry.path.startsWith("/"))
    .map((entry) => entry.path);
  return { ids, paths, at };
}

/** Kept for the page's lifetime: nothing observes the key, so it must never be collected. */
export function recordRemoval(client: QueryClient, removal: Removal): void {
  client.setQueryDefaults(REMOVALS_KEY, { gcTime: Number.POSITIVE_INFINITY });
  client.setQueryData<Removal[]>(REMOVALS_KEY, (old) => [...(old ?? []), removal]);
}

/** The removals after a scan began: that scan may still list what they deleted. */
export function removalsSince(client: QueryClient, startedAt: string | null): Removal[] {
  const all = client.getQueryData<Removal[]>(REMOVALS_KEY) ?? [];
  const started = startedAt === null ? Number.NaN : Date.parse(startedAt);
  if (Number.isNaN(started)) return all;
  return all.filter((removal) => removal.at > started);
}
```

- [ ] **Step 4: Run them to verify they pass**

Run (in `web/`): `bunx vitest run tests/unit/scanRows.test.ts tests/unit/cleanupRemovals.test.ts && bun run typecheck && bun run lint`
Expected: pass; lint adds no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/scanRows.ts web/src/lib/cleanupRemovals.ts web/tests/unit/scanRows.test.ts web/tests/unit/cleanupRemovals.test.ts
git commit -m "feat(web): record what a cleanup removed and drop it from a scan"
```

---

### Task 4: `useScan` drops later removals; scans start with the final filter

**Files:**
- Modify: `web/src/hooks/useScan.ts`
- Modify: `web/src/lib/providerFilters.ts`
- Modify: `web/src/pages/Scan.tsx`, `web/src/pages/Dashboard.tsx`
- Test: `web/tests/unit/useScan.test.tsx`, create `web/tests/unit/providerFilters.test.ts`

**Interfaces:**
- Consumes: `applyRemovals`, `ScanResult` (Task 3), `removalsSince`, `recordRemoval` (Task 3).
- Produces:
  - `useScan` accepts `enabled?: boolean`, and its data is a `ScanResult` including `startedAt`.
  - `diskScanReady(providers: Array<{ name: string }> | undefined, disabled: Set<string>): boolean`.

- [ ] **Step 1: Write the failing tests**

In `web/tests/unit/useScan.test.tsx`, add a wrapper bound to a client the test can reach, then the tests (import `recordRemoval` from `@/lib/cleanupRemovals` and `useScan` from `@/hooks/useScan` if not already imported):

```tsx
function clientWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
}

describe("useScan and cleanups", () => {
  const started = "2026-09-25T10:00:00+00:00";

  it("drops rows a cleanup removed after this scan began", async () => {
    const client = freshClient();
    recordRemoval(client, { ids: ["gone"], paths: [], at: Date.parse(started) + 60_000 });
    mockApiFetch.mockResolvedValue({
      entries: [entry("gone", 100, "safe"), entry("kept", 50, "safe")],
      scanned_at: "2026-09-25T10:02:00+00:00",
      started_at: started,
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { result } = renderHook(() => useScan(), { wrapper: clientWrapper(client) });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data!.rows.map((r) => r.id)).toEqual(["kept"]);
    expect(result.current.data!.startedAt).toBe(started);
  });

  it("keeps rows removed before this scan began: it saw the disk without them", async () => {
    const client = freshClient();
    recordRemoval(client, { ids: ["back"], paths: [], at: Date.parse(started) - 60_000 });
    mockApiFetch.mockResolvedValue({
      entries: [entry("back", 100, "safe")],
      scanned_at: "2026-09-25T10:02:00+00:00",
      started_at: started,
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { result } = renderHook(() => useScan(), { wrapper: clientWrapper(client) });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data!.rows.map((r) => r.id)).toEqual(["back"]);
  });

  it("sends nothing while it is not enabled", async () => {
    const client = freshClient();
    renderHook(() => useScan({ enabled: false }), { wrapper: clientWrapper(client) });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockApiFetch).not.toHaveBeenCalled();
  });
});
```

Create `web/tests/unit/providerFilters.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { diskScanReady } from "@/lib/providerFilters";

describe("diskScanReady", () => {
  it("is ready at once when nothing is disabled: the filter never depends on the list", () => {
    expect(diskScanReady(undefined, new Set())).toBe(true);
  });

  it("waits for the provider list when some are disabled", () => {
    expect(diskScanReady(undefined, new Set(["docker"]))).toBe(false);
  });

  it("is ready once the list has loaded", () => {
    expect(diskScanReady([{ name: "docker" }, { name: "uv-cache" }], new Set(["docker"]))).toBe(true);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `web/`): `bunx vitest run tests/unit/useScan.test.tsx tests/unit/providerFilters.test.ts`
Expected: FAIL: the removed row is still listed and `startedAt` is undefined; the disabled query calls `apiFetch`; `diskScanReady` is not exported.

- [ ] **Step 3: Implement**

`web/src/lib/providerFilters.ts`, append:

```ts
/**
 * Whether the disk scan's provider filter is final. It only depends on the
 * provider list when some are disabled; until that list loads, a scan would go
 * out unfiltered and then again filtered.
 */
export function diskScanReady(
  providers: Array<{ name: string }> | undefined,
  disabled: Set<string>,
): boolean {
  return disabled.size === 0 || providers !== undefined;
}
```

`web/src/hooks/useScan.ts`:
- import `useQueryClient` alongside `useQuery`;
- import `applyRemovals, type ScanCoverage, type ScanResult` from `@/lib/scanRows` (replacing the existing `ScanCoverage` type import);
- import `removalsSince` from `@/lib/cleanupRemovals`;
- add `started_at?: string | null;` to `ScanResponse`;
- add to `UseScanOptions`:

```ts
  /** False holds the request back, e.g. until the provider list that decides the filter has loaded. */
  enabled?: boolean;
```

Change the hook's start and the end of its `queryFn`:

```ts
export function useScan(params: UseScanOptions = {}) {
  const { staleTime, refetchOnMount, snapshotMinIntervalMs, enabled, ...filters } = params;
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["scan", filters],
    staleTime,
    refetchOnMount,
    enabled,
    queryFn: async (): Promise<ScanResult> => {
      // ... unchanged up to building `rows` ...
      const scan: ScanResult = {
        rows,
        totalBytes:
          raw.total_reclaimable_bytes ??
          rows
            .filter((entry) => entry.risk !== "dangerous")
            .reduce((sum, entry) => sum + (entry.reclaimable_bytes ?? 0), 0),
        scannedAt: raw.scanned_at,
        startedAt: raw.started_at ?? null,
        coverage: toCoverage(raw.coverage),
      };
      // A cleanup that finished after this scan began may have deleted rows it
      // still lists; they stay gone (spec: scan-dedupe §1).
      return applyRemovals(scan, removalsSince(queryClient, scan.startedAt));
    },
  });
}
```

`web/src/pages/Scan.tsx`:
- import `diskScanReady` with `diskProviderParam`;
- after `effectiveProviderParam`, add `const scanReady = providerQuery !== undefined || diskScanReady(providers, disabled);`;
- pass `enabled: scanReady` to `useScan`;
- show the loading block while not ready: replace `{isLoading && (` with `{(isLoading || !scanReady) && (`, and `{!isLoading && !error && (` with `{!isLoading && scanReady && !error && (`.

`web/src/pages/Dashboard.tsx`:
- import `diskScanReady`;
- compute `const diskScanReadyNow = diskScanReady(diskProviders.data, selectedDiskProviders.disabled);`;
- pass `enabled: diskScanReadyNow` to its `useScan` call;
- make the loading state follow it: `const diskLoading = diskPanelLoading(disk.isLoading || !diskScanReadyNow, diskSummary.data);`.

- [ ] **Step 4: Run them to verify they pass**

Run (in `web/`): `bun run test && bun run typecheck && bun run lint`
Expected: all unit tests pass (the existing `useScan` tests included); lint has no new errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/useScan.ts web/src/lib/providerFilters.ts web/src/pages/Scan.tsx web/src/pages/Dashboard.tsx web/tests/unit/useScan.test.tsx web/tests/unit/providerFilters.test.ts
git commit -m "fix(web): a scan keeps a cleanup's deletions out and starts with its final filter"
```

---

### Task 5: The wizard drops what it removed instead of rescanning

**Files:**
- Modify: `web/src/hooks/useCleanupWizard.ts` (the `done` listener in `openStream`)
- Test: `web/tests/unit/useCleanupWizard.test.ts`

**Interfaces:**
- Consumes: `removalFrom`, `recordRemoval` (Task 3), `applyRemovals`, `ScanResult` (Task 3).

- [ ] **Step 1: Write the failing test** (append inside `describe("useCleanupWizard", ...)`; import `type ScanResult` from `@/lib/scanRows`)

```ts
  // A full rescan after every cleanup was how two identical scans ended up running at once.
  it("drops what a cleanup removed from the cached scans instead of rescanning", async () => {
    const qc = new QueryClient();
    const cleaned = { ...ENTRY, footprint_bytes: 100, reclaimable_bytes: 100, shared_bytes: 0, owner: null, group: null, perms: null };
    const other = { ...cleaned, id: "p:/y", path: "/y", label: "other" };
    const scan: ScanResult = {
      rows: [cleaned, other],
      totalBytes: 200,
      scannedAt: "2026-09-25T10:00:00+00:00",
      startedAt: "2026-09-25T09:59:00+00:00",
      coverage: null,
    };
    qc.setQueryData(["scan", {}], scan);
    qc.setQueryData(["history"], []);
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useCleanupWizard({ entries: [cleaned] }), { wrapper });

    await act(async () => {
      await result.current.startJob();
    });
    act(() =>
      FakeEventSource.instances[0].emit("done", {
        results: [{ entry_id: cleaned.id, status: "ok", freed_bytes: 100 }],
      }),
    );

    const after = qc.getQueryData<ScanResult>(["scan", {}])!;
    expect(after.rows.map((r) => r.id)).toEqual(["p:/y"]);
    expect(after.totalBytes).toBe(100);
    expect(qc.getQueryState(["scan", {}])!.isInvalidated).toBe(false);
    expect(qc.getQueryState(["history"])!.isInvalidated).toBe(true);
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run (in `web/`): `bunx vitest run tests/unit/useCleanupWizard.test.ts`
Expected: FAIL: both rows are still cached and the scan query is invalidated.

- [ ] **Step 3: Implement**

In `web/src/hooks/useCleanupWizard.ts`:
- import `recordRemoval, removalFrom` from `@/lib/cleanupRemovals`;
- import `applyRemovals, type ScanResult` from `@/lib/scanRows`.

In the `done` listener, replace

```ts
      // Refresh any view sitting on stale post-cleanup data. Invalidate rather
      // than refetch: consumers that aren't mounted just get marked stale.
      queryClient.invalidateQueries({ queryKey: ["scan"] });
      queryClient.invalidateQueries({ queryKey: ["history"] });
      queryClient.invalidateQueries({ queryKey: ["disk-usage"] });
```

with

```ts
      // What the cleanup removed leaves every cached scan now, and a scan still
      // running drops it when it lands (useScan), so nothing needs a full rescan:
      // that rescan was how two identical scans ended up running at once.
      const removal = removalFrom(results, entriesRef.current, Date.now());
      if (removal) {
        recordRemoval(queryClient, removal);
        queryClient.setQueriesData<ScanResult>({ queryKey: ["scan"] }, (data) =>
          data ? applyRemovals(data, [removal]) : data,
        );
      }
      queryClient.invalidateQueries({ queryKey: ["history"] });
      queryClient.invalidateQueries({ queryKey: ["disk-usage"] });
```

- [ ] **Step 4: Run the web checks**

Run (in `web/`): `bun run test && bun run typecheck && bun run lint`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/useCleanupWizard.ts web/tests/unit/useCleanupWizard.test.ts
git commit -m "fix(web): a finished cleanup drops its rows instead of starting a full rescan"
```

---

### Task 6: End-to-end: a cleanup's row disappears without a rescan

**Files:**
- Modify: `web/tests/e2e/disk.spec.ts`

- [ ] **Step 1: Write the spec** (append; import `path` from `node:path`, and `NODE_MODULES_BYTES`, `PROJECT_PROVIDER` from `./fixture`)

```ts
test("a finished cleanup drops its row without another scan", async ({ page }) => {
  await page.goto("/disk");
  const row = page.getByText(`${PROJECT_NAME}/node_modules`);
  await expect(row).toBeVisible();
  const scans: string[] = [];
  try {
    await page
      .getByRole("checkbox", { name: new RegExp(`^select ${PROJECT_PROVIDER} ${PROJECT_NAME}/node_modules$`) })
      .check();
    await page.getByRole("button", { name: /^clean up 1 item$/ }).click();
    page.on("request", (request) => {
      if (/\/api\/(disk\/)?scan(\?|$)/.test(request.url())) scans.push(request.url());
    });
    await page.getByRole("button", { name: "execute", exact: true }).click();
    await page.getByRole("button", { name: "[y]" }).click();
    await page.getByRole("button", { name: "yes, execute" }).click();
    await expect(page.getByText("Cleanup complete.")).toBeVisible();
    await page.getByRole("button", { name: "Close cleanup wizard" }).click();

    await expect(row).toHaveCount(0);
    expect(fs.existsSync(nodeModulesPath())).toBe(false);
    expect(scans).toEqual([]);
  } finally {
    // The specs after this one expect the fixture as serve.ts built it.
    fs.mkdirSync(path.join(nodeModulesPath(), "pkg"), { recursive: true });
    fs.writeFileSync(path.join(nodeModulesPath(), "pkg", "index.js"), Buffer.alloc(NODE_MODULES_BYTES, 2));
  }
});
```

- [ ] **Step 2: Prove it discriminates**

Temporarily restore the old invalidation: add `queryClient.invalidateQueries({ queryKey: ["scan"] });` back into the `done` listener. Run (in `web/`) `bun run test:e2e`.
Expected: this spec FAILS on `expect(scans).toEqual([])`, because the Disk page rescans. Remove the line again.

- [ ] **Step 3: Run the full e2e suite**

Run (in `web/`): `bun run test:e2e`, then `git checkout -- src/devdoctor/web/_static/dist/index.html` from the repo root.
Expected: all specs pass (13, with this one).

- [ ] **Step 4: Commit**

```bash
git add web/tests/e2e/disk.spec.ts
git commit -m "test(e2e): a cleanup's row leaves the Disk page without a rescan"
```

---

### Task 7: CHANGELOG and final verification

**Files:**
- Modify: `CHANGELOG.md` (`## [Unreleased]` → `### Fixed`, first bullet)

- [ ] **Step 1: Add the entry**

```markdown
- **Two identical scans no longer run at once.** A finished cleanup started a
  full rescan (75–100 s on the reference machine) even while one was running,
  and concurrent scans slowed each other about 5×. The Disk page now drops what
  a cleanup removed straight away, and a scan that was already running cannot
  bring it back. The server runs one scan per filter set, which later requests
  for the same filters share. With providers disabled, the first scan waits for
  the provider list instead of running unfiltered and then again filtered.
```

- [ ] **Step 2: Run everything**

Run:
- `.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy && .venv/bin/python -m pytest -q -p no:cacheprovider`;
- in `web/`: `bun run lint && bun run typecheck && bun run test && bun run build && bun run test:e2e`;
- then `git checkout -- src/devdoctor/web/_static/dist/index.html`.

Expected: all green; lint 0 errors.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): one scan at a time, and no rescan after a cleanup"
```
