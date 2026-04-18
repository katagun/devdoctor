# diskdoctor web UI — Design

Date: 2026-04-18
Status: Draft v1

Companion to [`2026-04-18-diskdoctor-design.md`](2026-04-18-diskdoctor-design.md). Read that first — this doc extends the same system.

## Purpose

Add a local web UI on top of the diskdoctor CLI so the user can scan, review, clean up, and track their machine's disk caches visually. Core daily workflow is single-user, single-machine: `diskdoctor serve` launches a local FastAPI server, opens the default browser, and provides the full surface — scan table, interactive cleanup wizard, snapshots/diff, providers — with the same safety model as the CLI (dry-run-first, DANGEROUS gated, commented recipe exports).

## Non-goals

- Not multi-user, not networked, not authenticated. Binds `127.0.0.1` only.
- Not a dashboard for multiple machines.
- Not a replacement for the CLI. The CLI remains the canonical interface; the web UI is a thin adapter over the same Python domain.
- No telemetry, no analytics, no remote state.
- Not a Windows tool (matches the parent spec).

## Top-level decisions

| Decision | Choice |
|---|---|
| Scope | Full parity + interactive cleanup wizard |
| Deployment | Single-user, `127.0.0.1`-only, no auth |
| Visual direction | Terminal Refined (dark, JetBrains Mono for data) with richer three-colour risk palette: green/purple/red |
| Layout | Left sidebar + main; sticky top-stats strip |
| Cleanup wizard | Three steps: Review → Execute → Summary; per-entry toggles; live streamed console |
| Frontend framework | React + Vite + TypeScript |
| Styling | Tailwind v4 + shadcn/ui primitives; palette via CSS variables |
| Component library additions | TanStack Query (server cache), Recharts (sparkline), TanStack Virtual (table at ≥200 rows) |
| Real-time | SSE (`sse-starlette`); no WebSockets in v1 |
| Repo layout | Monorepo, same package; frontend lives in `web/`, built into `src/diskdoctor/web/_static/dist/` |
| Packaging | `npm run build && uv build`; the built SPA is bundled in the wheel via hatchling `force-include` |
| Launch | `diskdoctor serve [--port N --no-browser]` subcommand |

## Architecture

One process. Two languages. One test seam.

```
┌─────────────────── Browser ───────────────────┐
│ React SPA (Vite build → _static/dist/)        │
│  — TanStack Query → fetch /api/*              │
│  — EventSource → /api/*/stream                │
└────────────┬──────────────────────────────────┘
             │
             ▼ HTTP + SSE
┌───────── FastAPI (uvicorn, 127.0.0.1) ────────┐
│  routes_scan.py    ─┐                         │
│  routes_clean.py   ─┼─▶  Python domain        │
│  routes_history.py ─┘     (unchanged v1 API)  │
│  StaticFiles(_static/dist/) mounted at /      │
└────────────┬──────────────────────────────────┘
             │
             ▼
┌──── Python domain (src/diskdoctor/) ──────────┐
│  discovery.scan   cleanup.run   history.*     │
│  registry.load_providers(shell)               │
│  Shell port (one seam, unchanged)             │
└───────────────────────────────────────────────┘
```

**Reuse, don't re-implement.** The web layer is a thin adapter. Every route calls existing domain functions. `Report.to_json()` is the wire format. `registry.load_providers(shell)` constructs providers exactly like the CLI. `cleanup.run()` runs unchanged — the web layer just supplies different `PromptChoice` and `Confirm` callables (async-gated queues instead of Rich prompts).

**The only domain change in v1:** `Shell.run` gains an optional `stream: Callable[[str, str], Awaitable[None]] | None` kwarg for line-by-line stdout/stderr streaming. `RealShell` reads the subprocess pipes incrementally when the callback is present; otherwise falls back to the current synchronous `subprocess.run` path. `FakeShell` accepts the kwarg and ignores it (no-op) to stay backward compatible with all v1 tests. Existing call sites pass no streaming callback, so their behavior is unchanged.

## Repo layout

```
diskdoctor/
├── src/diskdoctor/                     existing — unchanged unless noted
│   ├── cli.py                          + `serve` subcommand
│   ├── cleanup.py                      Provider.run accepts optional streaming Shell callback
│   ├── ports.py                        Shell.run grows optional `stream` kwarg; RealShell implements
│   └── web/                            NEW
│       ├── __init__.py
│       ├── app.py                      build_app(shell) → FastAPI; wires routes + static mount
│       ├── routes_scan.py              /api/scan, /api/scan/stream, /api/providers
│       ├── routes_clean.py             /api/clean/jobs, /answer, /confirm, /cancel, /events
│       ├── routes_history.py           /api/snapshots, /api/snapshots/<name>, /api/diff
│       ├── routes_recipe.py            /api/recipe
│       ├── job_registry.py             in-memory CleanJob registry (one active job)
│       ├── models.py                   pydantic request models (output uses Report.to_json)
│       └── _static/dist/               built SPA assets (git-ignored; filled by vite build)
├── web/                                NEW — frontend source
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── theme.css                   Terminal Refined palette as CSS variables
│   │   ├── index.css                   Tailwind v4 @theme inline tokens
│   │   ├── AppShell.tsx                sidebar + router outlet + top stats strip
│   │   ├── pages/
│   │   │   ├── Scan.tsx
│   │   │   ├── Snapshots.tsx
│   │   │   └── Providers.tsx
│   │   ├── components/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── TopStats.tsx
│   │   │   ├── CacheTable.tsx
│   │   │   ├── RiskBadge.tsx
│   │   │   ├── CleanWizard/
│   │   │   │   ├── index.tsx           orchestrates the three steps
│   │   │   │   ├── ReviewStep.tsx
│   │   │   │   ├── ExecuteStep.tsx
│   │   │   │   ├── SummaryStep.tsx
│   │   │   │   └── CleanJobContext.tsx
│   │   │   ├── DiffTable.tsx
│   │   │   └── ui/                     shadcn components (copied-in)
│   │   ├── hooks/
│   │   │   ├── useScan.ts              TanStack Query wrapper
│   │   │   ├── useProviders.ts
│   │   │   ├── useSnapshots.ts
│   │   │   ├── useDiff.ts
│   │   │   ├── useSSE.ts               EventSource wrapper
│   │   │   └── useCleanJob.ts          wizard state machine
│   │   ├── api/
│   │   │   ├── client.ts               fetch helpers; base URL + error envelope
│   │   │   └── types.ts                mirrors Report, Entry, CleanResult…
│   │   └── lib/
│   │       └── format.ts               humanBytes, risk label, staleness (matches rendering.py semantics)
│   └── tests/
│       ├── unit/                       Vitest
│       └── e2e/                        Playwright smoke test (serve → scan → preview clean)
├── pyproject.toml                      + fastapi, uvicorn[standard], sse-starlette; web extras
├── .gitignore                          + web/node_modules, web/dist, src/diskdoctor/web/_static/dist
└── (everything else from v1)
```

### `pyproject.toml` additions

```toml
[project.optional-dependencies]
web = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sse-starlette>=2.1",
  "starlette>=0.38",
]

[tool.hatch.build.targets.wheel.force-include]
"src/diskdoctor/data/paths.yaml" = "diskdoctor/data/paths.yaml"
"src/diskdoctor/web/_static/dist" = "diskdoctor/web/_static/dist"
```

`uv tool install .` with no extras still works (web imports are deferred to the `serve` subcommand). `uv tool install '.[web]'` pulls FastAPI etc. The `serve` command imports lazily and errors clearly if the `web` extra is missing: *"Install with `uv tool install '.[web]'` to use the web UI."*

The `src/diskdoctor/web/_static/dist/` directory is required to exist at build time (hatchling's `force-include` fails otherwise, same as the `paths.yaml` pattern in v1). The repo ships an `src/diskdoctor/web/_static/dist/.keep` file plus a placeholder `index.html` so fresh clones build without running the frontend first. `npm run build` overwrites the placeholder. Distribution wheels always carry the real built SPA.

## HTTP API

All endpoints under `/api/*`. JSON request bodies with pydantic validation. Responses use the existing `Report.to_json()` / `DiffReport`-derived schemas — no duplicate DTO hierarchy.

### Scan & providers

```
GET  /api/scan?min_size=<str>&risk=<csv>&provider=<csv>&fresh=0|1
  Returns: Report (full JSON)
  Cached in-process 5s; ?fresh=1 bypasses. Any successful POST /api/clean/jobs completion invalidates.

GET  /api/scan/stream
  SSE. Emits one event per provider completion, then a terminal `done` event.
    event: "provider" data: {name, entries: Entry[], elapsed_ms, skipped: string[]}
    event: "done"     data: Report
  Useful for pages that want live row streaming during a scan of many providers.

GET  /api/providers
  Returns: ProviderInfo[]
    { name, description, risk, platforms, available: bool,
      required_binary: string | null, kind: "class" | "yaml",
      reason_if_unavailable: string | null }
```

### Recipe

```
POST /api/recipe
  body: { providers?: string[] }
  Returns: { script: string }  — always commented-out, matches cleanup.build_script.
```

### Cleanup

```
POST /api/clean/jobs
  body: { entry_ids: string[], yes_safe?: boolean, allow_dangerous?: boolean }
  Returns: { job_id: string }
  If a job is already running → 409 { error: { code: "job_in_progress", ... } }

GET  /api/clean/jobs/<id>/events
  SSE stream of the wizard lifecycle (see §3 of brainstorm + below).

POST /api/clean/jobs/<id>/answer
  body: { entry_id: string, choice: "y" | "n" | "a" | "s" | "q" }
  Unblocks the server-side PromptChoice wait. 204 No Content.

POST /api/clean/jobs/<id>/confirm
  body: { confirmed: boolean }
  Unblocks the server-side Confirm wait. 204 No Content.

POST /api/clean/jobs/<id>/cancel
  Marks remaining entries as skipped (reason: "cancelled") and terminates the job cleanly. 204.
```

**Clean job SSE event catalogue.** Emitted by `/api/clean/jobs/<id>/events` in order:

```
event: "prompt"              data: { entry_id, label, risk, size_bytes, recipe: string[] }
event: "awaiting_confirm"    data: { summary: string, approved_ids: string[], total_bytes }
event: "execute_start"       data: { entry_id, cmd: string }
event: "execute_progress"    data: { entry_id, stream: "stdout" | "stderr", chunk: string }
event: "execute_result"      data: { entry_id, status: "ok"|"skipped"|"error"|"dry_run", freed_bytes, message? }
event: "done"                data: { results: CleanResult[] }
event: "error"               data: { code, message, hint? }   # only on unrecoverable failure; stream closes
```

The server emits `prompt` events for each entry that needs a user choice (DANGEROUS-without-allow, yes-safe auto-approved, and earlier-"a"/"s"-overridden entries skip the prompt server-side and go straight to either execute or skipped-in-results — matching `cleanup.run`'s existing precedence). The client resolves each `prompt` with a `POST /answer` before the job proceeds.

### History

```
GET  /api/snapshots
  Returns: SnapshotMeta[]  { path, name, scanned_at, hostname, platform, note, total_bytes }
  Read from history.default_snapshot_dir(); sorted desc.

POST /api/snapshots
  body: { note?: string }
  Runs a scan, writes a snapshot, returns { path, name }.

GET  /api/snapshots/<name>
  Returns: Report JSON (the snapshot contents).

GET  /api/diff?from=<name>&to=<name | "live">
  Returns: DiffReport JSON.
```

### Error envelope

Any unhandled server exception → `500 { error: { code, message, hint? } }`. Validation errors → `422 { error: { code: "validation", message, fields: {...} } }`. Conflict (job already running) → `409`. Missing snapshot → `404`.

## Clean-job state machine (server side)

A `CleanJob` is an asyncio task with:

- an outbound `asyncio.Queue[Event]` consumed by the SSE route,
- a `dict[str, asyncio.Future[Choice]]` of pending per-entry answers,
- an `asyncio.Future[bool]` for the final confirm.

The job runs `cleanup.run(report, shell, prompt_choice=<adapter>, confirm=<adapter>, opts=...)` inside a worker task. The adapter callables look roughly like:

```python
async def prompt_choice(entry: Entry) -> Choice:
    await job.queue.put({"event": "prompt", "data": serialize(entry)})
    job.pending[entry.id] = asyncio.get_event_loop().create_future()
    return await job.pending[entry.id]  # unblocked by POST /answer

async def confirm(message: str) -> bool:
    await job.queue.put({"event": "awaiting_confirm", "data": {"summary": message, ...}})
    job.confirm_future = asyncio.get_event_loop().create_future()
    return await job.confirm_future
```

Because `cleanup.run` currently takes *sync* callables, v1 adds a sibling `cleanup.run_async` entry point that accepts awaitable `PromptChoice` / `Confirm` callables and uses `await` at the same points. This is the second (and only other) domain change — not a rewrite of the existing `run`. Rationale: keeping the sync `run` pristine preserves the CLI's current behavior and its 15 cleanup tests exactly as-is, while the web backend has a first-class async path that matches its event-loop model.

The job registry holds at most one active job. Completed jobs persist in memory for 60 seconds so the client can reconnect to replay the `done` event if the SSE stream dropped. After 60s the job GC runs.

## Frontend state

Three tiers, each with a clear owner:

- **Server cache → TanStack Query.** Hooks: `useScan`, `useProviders`, `useSnapshots`, `useDiff`. Stale times: scan 5s, providers 60s, snapshots on-mount. Mutations (snapshot create, recipe download) invalidate their key.
- **Wizard / job → `CleanJobContext`.** Lives under `<CleanWizard/>`. Holds `{step, entries, selection, jobId, events, error}`. Dies when the wizard unmounts. Never global.
- **UI-local → URL querystring + localStorage.** Risk filter, search text, group/flat toggle, sort column all live in `?risk=…&q=…&group=…&sort=…`. Sidebar collapsed state in localStorage.

No Redux / Zustand / global context provider above `AppShell` except `QueryClientProvider`.

## Theming

Single stylesheet `web/src/theme.css` declares the Terminal Refined palette as CSS variables. Tailwind v4 reads them via `@theme`.

```css
:root[data-theme="terminal-refined"] {
  --bg:           #0b0e13;
  --bg-elev-1:    #0d1218;
  --bg-elev-2:    #13181f;
  --border:       #1a2128;
  --text:         #d7e3e8;
  --text-dim:     #8a9aa8;
  --text-muted:   #566876;
  --risk-safe:    #7fe4b1;
  --risk-reclaim: #c4a5ff;
  --risk-danger:  #ff8897;
  --accent:       #7fe4b1;
  --font-mono:    "JetBrains Mono", ui-monospace, SFMono-Regular, Consolas, monospace;
  --font-ui:      "Inter", system-ui, -apple-system, sans-serif;
}
```

```css
/* web/src/index.css */
@import "tailwindcss";
@import "./theme.css";

@theme inline {
  --color-bg: var(--bg);
  --color-border: var(--border);
  --color-risk-safe: var(--risk-safe);
  --color-risk-reclaim: var(--risk-reclaim);
  --color-risk-danger: var(--risk-danger);
  --font-mono: var(--font-mono);
  --font-sans: var(--font-ui);
}
```

shadcn's default Radix-coloured classes are overridden by editing the copied-in `components/ui/*.tsx` files — the single place we touch shadcn internals. Future `data-theme="light"` adds a companion palette; nothing else changes.

## UX details & non-visual behaviours

**Launch (`diskdoctor serve`)**:
- Binds `127.0.0.1:<port>`; port is `--port N` or a random free port.
- Opens the default browser via `webbrowser.open` unless `--no-browser`.
- `--dev` disables the SPA static mount (expects Vite dev server to serve `/`). Also sets CORS to allow `http://localhost:5173`.
- Prints the URL and a "Ctrl-C to stop" line. `SIGINT` shuts down cleanly.
- Refuses to start with a clear error if the web extras are missing.

**Loading / empty / error states** (every data view):
- Loading → skeleton rows matching the final table geometry (8 placeholder rows).
- Empty (with filters) → "(no entries match your filters)" with one-click "clear filters" link.
- Empty (truly nothing) → "Nothing to reclaim. Your disk is in good shape." with timestamp.
- Provider unavailable → grey dot + tooltip reason. No red for "not installed".
- Scan in progress → rows stream in via `/api/scan/stream`; each arrives with a one-time flash animation; top stats update live.
- Clean job running → wizard takes over the main content area; sidebar shows a job badge; clicking anywhere in the sidebar reopens the wizard.
- Network error → non-blocking toast + retry button; auto-retry on reconnect.
- Fatal 500 → full-page error with the error envelope displayed + "Copy diagnostic" button.

**Keyboard**:
- `/` focuses the filter search input.
- `Space` toggles the selected row's checkbox.
- `Shift+click` selects a range.
- `Esc` closes the wizard (guarded with a confirm if mid-execute).
- `⌘K` — stubbed in v1 (opens a "coming soon" hint), full palette is a v2 task.

**Table performance**:
- Virtualised above 200 rows via TanStack Virtual.
- Row heights fixed so the virtualiser doesn't thrash.
- Cold-scan of the author's machine today finishes in 0.4s; we target ≤1s for "scan → first row visible" on a reasonable laptop. The SSE stream enables an even earlier first paint of the initial providers.

**Bundle budget**: initial JS ≤150 KB gzipped. React + TanStack Query + Radix primitives + Recharts (tree-shaken to LineChart) + our app fit comfortably. Vite's default code-splitting separates the wizard and snapshots routes.

## Error handling

| Failure | Server response | Client behavior |
|---|---|---|
| Provider's `available()` False | Included in Report with `unavailable` marker; HTTP 200 | Row shown greyed with tooltip |
| Provider raised inside discover() | Caught, reported in `Report.skipped_paths` | Footer note: "N providers errored" |
| Scan timeout (provider hangs >30s) | Provider marked unavailable, scan completes | Row shown greyed, reason "timed out" |
| Clean job: shell command fails | CleanResult(status="error"); job continues | Execute step marks ✗ on that entry, keeps going |
| Clean job: user cancels mid-execute | Remaining marked skipped, job terminates cleanly | Wizard jumps to Summary with partial results |
| Clean job: server crashes mid-execute | SSE stream closes; job lost | Client shows "Connection lost" toast with retry; on retry, client sees no active job and prompts user to rescan |
| Second concurrent `POST /api/clean/jobs` | 409 Conflict | Toast: "A cleanup is already in progress" |
| Snapshot file malformed | 500 with error envelope | Toast on Snapshots page |
| SSE reconnection | Replays the last `done` or `error` event if within 60s window | Transparent to user |

## Testing

Existing Python v1 tests continue unchanged. New tests:

**Backend (pytest)**:
- `tests/web/test_routes_scan.py` — `/api/scan` happy path, filter passthrough, `?fresh=1` bypasses cache; `/api/scan/stream` emits provider events + done.
- `tests/web/test_routes_clean.py` — full job lifecycle with `FakeShell`: POST job → consume SSE → POST /answer for each prompt → POST /confirm → assert final `done` event matches synchronous `cleanup.run` output for the same inputs.
- `tests/web/test_routes_history.py` — snapshot write/list/get + diff round-trip.
- `tests/web/test_job_registry.py` — second-concurrent job rejected with 409; job GC after 60s.
- `tests/web/test_shell_streaming.py` — `RealShell.run(stream=cb)` yields stdout/stderr chunks in order; falls back to non-streaming when `stream=None`.
- `tests/web/test_serve_cli.py` — `diskdoctor serve --help`; error message when web extras not installed.

Coverage targets: web routes ≥85%, job registry ≥90%, shell streaming ≥90%.

**Frontend (Vitest)**:
- `web/tests/unit/format.test.ts` — `humanBytes`, `staleness` match the Python `rendering.py` outputs exactly.
- `web/tests/unit/hooks/useSSE.test.ts` — EventSource mocked; status transitions; reconnect logic.
- `web/tests/unit/hooks/useCleanJob.test.ts` — state machine drives through a scripted sequence of prompt/confirm/execute events and reaches `done`.
- `web/tests/unit/components/RiskBadge.test.tsx`, `CacheTable.test.tsx` — rendering + interaction.

**Frontend (Playwright, smoke only)**:
- One test: launch `diskdoctor serve --port 8731 --no-browser`, hit the URL with Playwright, assert the scan view loads, trigger a preview-mode (dry-run) clean job end-to-end, assert the Summary step shows the expected counts. Uses a controlled `paths.yaml` via `DISKDOCTOR_PATHS_YAML` so the test is deterministic.

## Security considerations

- **Bind address**: `127.0.0.1` only. Refuse `0.0.0.0`. A future `--host` flag (not in v1) would require also setting a bearer token.
- **CORS**: default off. Dev mode allows `http://localhost:5173` only.
- **SSRF**: no server-side URL fetching; no user-supplied URLs anywhere.
- **Input validation**: pydantic on every POST body. `entry_ids` validated against the currently-known scan results (in-process set); unknown IDs are 400.
- **Shell injection**: continues to use `entry.recipe` strings built by `cleanup.run`, which in turn uses the `shlex.quote`-tested path interpolation from the v1 providers. No new interpolation in the web layer.
- **Concurrency**: one clean job at a time (hard invariant); scan is idempotent and parallel-safe with running clean.
- **Shutdown**: `SIGINT` terminates uvicorn gracefully; any active clean job receives a cancel signal; in-flight subprocesses are allowed to finish (no orphaned children).

## Out of scope for v1

- Authentication / multi-user.
- Remote-host scanning.
- Dark / light theme toggle (palette declared in a way that permits v2 light theme with zero structural change).
- `⌘K` command palette (stub only).
- Drag-to-group, column hide/show, CSV export.
- WebSocket upgrade.
- Native menu-bar / tray app wrapper.

## Future extensions

- `⌘K` palette (Cmd-K Menu + quick actions).
- Light theme (add `data-theme="light"`).
- Per-provider history charts (Recharts line over the last N snapshots).
- WebSocket upgrade for cancel-mid-line-of-recipe execution.
- PWA wrapper for add-to-dock on macOS.
- `diskdoctor serve --tray` — tiny menu-bar helper that opens the UI on click.

## Key design choices (and what was considered)

- **Reuse Python domain, don't re-model on the wire.** Earlier drafts had a DTO layer; dropped. `Report.to_json()` is the single source of truth and already used by `--json` and snapshots. Any field the CLI exposes, the web gets for free.
- **One port still (`Shell`).** Other tempting abstractions (an `AsyncIO`-native provider interface, an async registry) were rejected — we add one async `cleanup.run` sibling and one optional `stream` kwarg on `Shell.run`. That's it.
- **SSE over WebSockets.** One-way data flow today. If cancel-mid-shell-command becomes important later, WebSockets replace SSE in a single route file.
- **Monorepo, no separate npm package.** diskdoctor is one app; shipping two version-locked releases is needless overhead. Users install with one `uv tool install .` and never touch Node.
- **State lives where it belongs.** Server cache in TanStack Query; wizard state scoped to the wizard tree; UI state in the URL. No global store.
- **Palette via CSS variables.** Tailwind v4 lets us keep CSS-variable-driven theming without fighting the utility-class model. Future light theme is a variable-swap, not a rewrite.
