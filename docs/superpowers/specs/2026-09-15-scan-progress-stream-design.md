# Stream scan progress per provider — Design

**Issue:** [#117](https://github.com/katagun/devdoctor/issues/117)
(split out of [#104](https://github.com/katagun/devdoctor/issues/104), part 3)
**Status:** approved design, 2026-09-15

## 1. Problem

The web Disk page renders nothing until `discovery.scan` returns. On a machine
where a full scan takes 150–160 s the only feedback is the estimate from past
scans (#104 made it count down and float above the newest scan, but it is still
a guess), and the user cannot tell which provider is running, how much has been
found, or whether the scan is stuck.

The scan runs every available provider in a thread pool and only then
reconciles hard-linked usage, applies git-worktree containment, sorts, and
filters. Rows are therefore not final until every provider has finished:
containment can remove entries, and reconciliation can change reclaimable
bytes.

## 2. Decisions

1. **Progress, not preliminary rows.** The page shows which providers are
   pending, running and done, with entries and bytes found so far; the table
   still appears once, exact, when the scan returns. Preliminary rows are a
   possible follow-up once the stream exists.
2. **Side channel, not a new scan path.** `GET /api/scan` stays the scan and
   keeps its contract (snapshots, dashboard summary, CLI parity). A new
   `GET /api/scan/progress` server-sent-events endpoint mirrors the scan that is
   running in the server process. Nothing about how scan data reaches the page
   changes.
3. **The hook lives in `discovery`.** `discovery.scan` gains an optional
   progress callback so the web route can observe the scan without wrapping
   providers. The CLI keeps its current output; it can adopt the same callback
   later.
4. **Progress is decoration.** A missing, late or broken stream never affects
   the scan or the page's data; the page then behaves exactly as today.

## 3. Discovery hook

`discovery.scan(providers, filters, now, *, contain=True, on_progress=None)`.

`on_progress: ScanProgressCallback | None`, where
`ScanProgressCallback = Callable[[ScanProgressEvent], None]` and
`ScanProgressEvent = ScanStarted | ProviderStarted | ProviderFinished`, three
frozen dataclasses in `discovery.py`:

| Event | When | Thread | Fields |
|---|---|---|---|
| `ScanStarted` | once, after availability is frozen, before the pool starts | caller | `providers: tuple[str, ...]` — available provider names in provider order |
| `ProviderStarted` | at the top of `_discover_one` | worker | `name: str` |
| `ProviderFinished` | when `_discover_one` returns, including the failure path | worker | `timing: ProviderTiming` — the pre-containment timing `_discover_one` already builds; a failed provider reports `entries=0, bytes=0` |

Rules:

- The callback is invoked through one helper that catches every exception,
  logs it once at warning level with the event name, and continues. A broken
  consumer cannot abort or alter a scan.
- Events may arrive from several threads at once; the consumer is responsible
  for its own locking.
- `ProviderFinished.timing` is what `_discover_one` computed: bytes and entries
  before reconciliation and containment. It is right for "found so far"; the
  report's totals still come only from `scan()`'s return value.
- No event is emitted after `scan()` returns; the consumer treats the last
  `ProviderFinished` as the end of provider work. Post-processing (reconcile,
  contain, sort, filter) has no events.

## 4. Hub

`src/devdoctor/web/scan_progress.py`, `ScanProgressHub`, created in
`build_app` as `app.state.scan_progress`.

- `observer() -> ScanProgressCallback` allocates the next `scan_id` (an
  increasing integer starting at 1) and returns a callback bound to it. Events
  carrying an older `scan_id` than the hub's current one are ignored, so when
  two scans overlap the hub shows the newest.
- `snapshot() -> ScanProgressSnapshot` (frozen dataclass, serialised to JSON
  by the route):

  ```
  scan_id: int             # 0 while idle
  status: "idle" | "running" | "done"
  started_at: datetime | None
  total: int               # len(ScanStarted.providers)
  done: int
  running: tuple[str, ...] # names with status "running", provider order
  entries: int             # sum over finished providers
  bytes: int               # sum of ProviderTiming.bytes over finished providers
  providers: tuple[ProviderProgress, ...]
      # ProviderProgress: name, status "pending"|"running"|"done",
      #   duration_ms: int | None, entries: int, bytes: int
  ```

- `version: int` increments on every accepted event. A lock guards state and
  version together.
- `ScanStarted` resets the state to `running` with every provider `pending`;
  `ProviderStarted` marks one `running`; `ProviderFinished` marks it `done` and
  adds its figures; when `done == total` the status becomes `done`. An
  `ScanStarted` with no providers goes straight to `done`.

## 5. Endpoint

`GET /api/scan/progress` → `EventSourceResponse` with `ping=10`, like
`/api/clean/jobs/{id}/events`.

- Sends the current snapshot immediately as event `progress`, data = the
  snapshot as JSON (`started_at` ISO-8601 or null; tuples as arrays).
- Then, every 200 ms, compares the hub version with the last one sent and
  sends a new `progress` event on change.
- Ends after a transition into `done` it observed itself (from `running`, or
  straight from `idle` for a scan with no available providers). An initial
  snapshot that is already `done` or `idle` does not end the stream: the
  client's own scan may not have reached the server yet. The client closes the
  stream when its fetch completes, and a closed connection ends the generator
  with nothing to clean up.
- Only `/api/scan` and its alias `/api/disk/scan` pass
  `on_progress=hub.observer()`. The cleanup wizard's containment-off scan and
  the recipe route report nothing.
- The endpoint is read-only and needs no new middleware or host rules.

## 6. Client

### 6.1 `useScanProgress(active: boolean): ScanProgressSnapshot | null`

`web/src/hooks/useScanProgress.ts`. While `active`:

- opens `new EventSource("/api/scan/progress")` and keeps the latest
  `progress` event's data;
- ignores `idle` snapshots and any snapshot whose `scan_id` is lower than the
  highest already kept, so a stale `done` from an earlier scan cannot show;
- closes the source when `active` turns false, on unmount, or on a `done`
  snapshot (which it keeps as the final value until `active` turns false);
- on `onerror`, keeps the last value and does not reconnect; when `active` turns
  false it returns `null` again.

### 6.2 `formatScanProgress(snapshot)` in `web/src/lib/scanProgress.ts`

Pure; returns `{ providers, found, running, finishing }`:

- `providers`: `"12/22 providers"`
- `found`: `"45.2 GB found"` (`humanBytes` of `bytes`); omitted while
  `done === 0`, so a scan whose first provider found nothing reads `"0B found"`
  rather than nothing
- `running`: `"running: a, b, c"` with at most three names then `" +N"`;
  omitted when nothing is running
- `finishing`: `true` when `status === "done"` — the caller shows
  `"finishing…"` while the query is still fetching

### 6.3 Where it renders

`Scan.tsx` calls `useScanProgress(isFetching)` and renders `ScanProgressLine`
(`web/src/components/ScanProgressLine.tsx`, props: `progress`,
`remainingMs`, `bar: boolean`):

- cold load (no rows yet): the loading block becomes
  `scanning… · 12/22 providers · 45.2 GB found · running: xcode-development-data, docker · ~1m 20s left, from past scans`
  with a thin `done/total` bar beneath (`role="progressbar"` with
  `aria-valuenow/max`);
- rescan (rows shown): the toolbar's `rescanning…` label carries the same
  parts, no bar;
- before the first snapshot, or with no stream, both places show exactly what
  they show today: `scanning…`/`rescanning…` plus the countdown.

`Dashboard.tsx` calls `useScanProgress(disk.isFetching)` and appends
`· 12/22 providers` to its disk panel's loading label; nothing else changes.

## 7. Failure modes

| Case | Behaviour |
|---|---|
| Consumer callback raises | Logged once per event, scan unaffected (§3) |
| Two scans overlap | Hub shows the newest `scan_id`; older events ignored (§4) |
| Stream connects before the scan starts | Initial `idle`/stale snapshot kept open; the running snapshot follows (§5) |
| Stream connects after the scan finished | Query completes; the client closes the stream on `isFetching` false |
| Client disconnects | Generator ends; no server state |
| EventSource error | Last value kept, no reconnect; page falls back to today's text |
| Provider fails | Reported as finished with zero figures; the diagnostic still reaches the report |

## 8. Testing

Every test is written before the code it covers and watched fail.

**pytest**

- `tests/test_discovery.py`: `on_progress` receives `ScanStarted` with the
  available names, then one `ProviderStarted`/`ProviderFinished` pair per
  available provider (order-independent, counted by name); a raising provider
  still yields `ProviderFinished` with `entries=0`; a raising callback leaves
  the returned report identical to a scan without a callback; no callback,
  no change.
- `tests/web/test_scan_progress.py`: snapshot after each event; `version`
  increments; events from an older `scan_id` are ignored; `done` when the last
  provider finishes; empty `ScanStarted` is `done` at once; concurrent events
  from threads leave consistent totals.
- `tests/web/test_routes_scan.py`: the stream sends an initial snapshot; driven
  by the hub it sends `running` then `done` and ends; an initial `done` does not
  end it; `/api/scan` reports through the hub (after a scan, the snapshot is
  `done` with the fixture provider's figures).

**vitest**

- `formatScanProgress` cases from §6.2.
- `useScanProgress` with a mocked `EventSource` (as `useSSE.test.ts` does):
  opens on `active`, closes on inactive/unmount/`done`, latest wins, `idle` and
  stale `scan_id` ignored, error keeps the last value.
- `ScanProgressLine` renders the parts and the bar's `aria` values.

**Playwright**

- The fixture scan finishes in milliseconds, so one spec holds `/api/scan`
  with `page.route` and fulfils `/api/scan/progress` with a canned
  `text/event-stream` body carrying two snapshots (1/3 then 3/3); it asserts
  the loading line shows `1/3 providers` then `finishing…`.
- One live check: `GET /api/scan/progress` answers `200` with
  `content-type: text/event-stream` and an initial `progress` event (read via
  `fetch` with a short abort, not `EventSource`).

## 9. Out of scope

- Preliminary rows before the scan returns.
- CLI progress output (the callback is ready for it).
- Cancelling a running scan.
- Progress for the cleanup wizard's containment-off scan or the recipe route.

## 10. Documentation

CHANGELOG "Added" entry; one sentence in the README's web-UI section on live
scan progress; #117 closes with the implementing PR.
