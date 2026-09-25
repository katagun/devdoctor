# One scan at a time, and no rescan after a cleanup

**Status:** proposed, awaiting review · **Date:** 2026-09-25 ·
**Related:** PR #153 (cleanup start off the event loop), #104 (one scan key shared
by the Dashboard and the Disk page), #117 (scan progress stream).

## Problem

On 2026-09-24 the desktop app's log shows two identical full scans running at once
(`GET /api/scan` on connections 54456 and 54474). Concurrent scans share the sizer's
four walk workers and the GIL, and slow each other about 5×. Measured on the reference
machine, a `node_modules` re-check took 39 s alone and 222 s during a full scan. The
full scan itself went from about 75 s to 365 s.

Duplicate scans come from three places:

1. **After every cleanup.** The wizard invalidates `["scan"]`, which starts a full
   rescan (75–100 s here) even while one is already running. `apiFetch` takes no
   abort signal, so the old request keeps going, and the server cannot stop a
   synchronous scan. Both run to the end.
2. **A key that changes on load.** With any provider disabled, `diskProviderParam`
   returns `undefined` until `/api/providers` has loaded. The Disk page and the
   Dashboard therefore start an unfiltered scan, then a filtered one, once the
   provider list arrives.
3. **Any other request for the same filters.** A second window, or a page that is
   remounted after its request was abandoned, starts its own scan of the same
   filters.

## Non-goals

- Stopping a scan midway. Walks run on threads and cannot be interrupted; cancelling
  them cooperatively inside the sizer is a separate change.
- Caching results across visits. The "Live" cadence still rescans on each visit.
- Scans outside `GET /api/scan`: the cleanup's own re-check (§6.4, fresh by design),
  manual snapshots and diff.
- Aborting superseded requests. Once §1 and §2 remove the triggers, a client has at
  most one scan request per filter set in flight. TanStack Query's abort signal would
  also cancel a scan when its page unmounts. It would throw away a result that the
  hourly and daily cadences reuse, so leaving the page mid-scan would cost another
  scan later.

## Design

### 1. After a cleanup, drop what it removed (client)

The wizard's `done` handler stops invalidating `["scan"]`. Instead it records a
**removal**:

- the ids of the results with status `ok`;
- those entries' paths, taken from the rows the wizard was opened with;
- the time the event arrived.

It then applies the removal to every cached `["scan", …]` result. A row is dropped
when its id is removed, or when its path equals or lies inside a removed path. The
path rule also covers entries that were deleted together with their worktree, which
resolve as `skipped` (§6.4). The totals follow the dropped rows:

- `totalBytes` loses their estimated reclaimable bytes (non-dangerous rows);
- coverage's classified and used bytes both lose their footprint.

`["history"]` and `["disk-usage"]` are still invalidated; both are cheap.

Removals stay in the query client (`["cleanup-removals"]`) for the life of the page,
and `useScan` applies every removal newer than a scan's `started_at` to that scan's
rows. A scan that was already running when the cleanup finished therefore cannot
bring the deleted rows back. A scan that started afterwards saw the disk without
them. The browser and the backend run on the same machine (the server only answers
`127.0.0.1`), so the event's arrival time and the report's `started_at` read the
same clock.

The shared function is `applyRemovals(result, removals)` in `web/src/lib/scanRows.ts`,
next to the other row filters.

### 2. Start with the final filters (client)

When any provider is disabled, the scan query waits (`enabled: false`) until
`/api/providers` has loaded, so its first request already carries the final
`provider` filter. The Disk page and the Dashboard use one helper, so they still
share one key (#104).

### 3. One scan per filter set at a time (server)

A `ScanCoalescer` on `app.state` is keyed by `ScanFilters` (a frozen dataclass, so it
is hashable):

- The first `GET /api/scan` for a key runs the scan: progress observer, dashboard
  summary, auto-snapshot, exactly as today.
- A request for the same key that arrives while that scan runs waits for it, and
  returns its report without scanning or writing anything itself.
- Different keys run independently.
- An error reaches every waiting request, and the next request starts afresh.

The request that runs the scan decides the snapshot parameters; a request that
waits uses its result. The web client sends the same parameters from every page.
Requests run on worker threads, so the coalescer uses a lock and a
`concurrent.futures.Future`.

## Safety review

- Nothing that deletes changes. The cleanup job's re-check still scans fresh (§6.4)
  and does not go through the coalescer.
- Rows a cleanup removed never reappear from an older scan, and a newer scan shows
  the disk as it is.
- A request that joins a running scan gets a report that started before it did, by
  at most one scan's duration. The page already shows "scanned … ago" from the
  report.

## Testing

- **Coalescer.**
  - Concurrent calls with one key run the scan once and all get its result.
  - Different keys run separately.
  - An error reaches every waiter and clears the key.
  - Sequential calls each scan.
- **Route.** Two concurrent `GET /api/scan` with a gated scan: one scan, both answer
  200 with the same entries, and the dashboard summary is written once.
- **Wizard.**
  - `done` drops removed rows by id and by path containment, adjusts `totalBytes` and
    coverage, and does not invalidate `["scan"]`.
  - `history` and `disk-usage` are still invalidated.
- **`useScan`.**
  - A result whose `started_at` is before a removal has the removed rows dropped; one
    that started after it keeps them.
  - With a provider disabled, no request goes out before `/api/providers` has loaded.
- **E2E.** In the fixture home, clean `e2e-app/node_modules`. Its row disappears, and
  `/api/scan` is not requested again.

## Rollout

One PR stacked on #153, which also changes `useCleanupWizard.ts`, with a CHANGELOG
entry.

## Open questions for review

- A scan that overlaps a cleanup still writes its auto-snapshot and the dashboard
  summary, including the deleted entries, as it does today. Skipping those writes
  when a cleanup finished after the scan started would keep history exact. I suggest
  doing it as a follow-up, and can fold it in here if you prefer.
