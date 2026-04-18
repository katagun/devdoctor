# diskdoctor web UI — Design

Date: 2026-04-18
Status: Draft v2 (post architectural review)

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

**Reuse, don't re-implement.** The web layer is a thin adapter. Every route calls existing domain functions. `Report.to_json()` is the wire format. `registry.load_providers(shell)` constructs providers exactly like the CLI.

**Two domain changes in v1:**

1. **Lift the cleanup state machine into a pure generator.** The current `cleanup.run` holds a lot of logic (selection loop, DANGEROUS gating, provider overrides, confirm gate, shell dispatch). We refactor that logic into a core iterator `cleanup.iter_cleanup_events(report, opts) -> Iterator[CleanupEvent]` that yields `PromptRequired(entry)` / `ConfirmRequired(summary)` / `ExecuteStep(entry, recipe_line)` and consumes answers via `.send()`. Two thin adapters sit over it: the existing sync `cleanup.run` (which wraps it to produce the current behavior and preserves every v1 test) and a new async `cleanup.run_async` (which `await`s the web-side callables). Both adapters are ≤40 lines; the core state machine is tested once.
2. **Add a web-only async subprocess helper** at `src/diskdoctor/web/subprocess_stream.py`. This helper uses `asyncio.create_subprocess_exec` and yields stdout/stderr lines as they arrive. **The `Shell` port is not modified**; an earlier draft extended `Shell.run` with a `stream` kwarg, which muddied the sync/async contract for every downstream consumer. The web layer uses this helper *instead of* `Shell.run` when executing a cleanup recipe; the CLI path keeps using `Shell.run` unchanged.

These changes are additive and localized. The 4 class providers, the sync `cleanup.run` path, the CLI, and all 93 v1 tests are untouched.

## Repo layout

```
diskdoctor/
├── src/diskdoctor/                     existing — unchanged unless noted
│   ├── cli.py                          + `serve` subcommand
│   ├── cleanup.py                      lift core state machine into iter_cleanup_events;
│   │                                   existing `run` becomes a 30-line adapter over it
│   │                                   (behavior preserved; all 15 cleanup tests still pass)
│   │                                   new `run_async` adapter sits alongside for the web path
│   ├── ports.py                        UNCHANGED — Shell stays sync-only
│   └── web/                            NEW
│       ├── __init__.py
│       ├── app.py                      build_app(shell) → FastAPI; wires routes + static mount;
│       │                                enforces Host-header check middleware (see Security)
│       ├── subprocess_stream.py        asyncio.create_subprocess_exec helper; line-by-line
│       │                                async iterator of (stream, chunk) pairs
│       ├── routes_scan.py              /api/scan, /api/providers, /api/recipe
│       ├── routes_clean.py             /api/clean/jobs, /answer, /confirm, /cancel, /events
│       ├── routes_history.py           /api/snapshots, /api/snapshots/<name>, /api/diff
│       ├── cleanup_runner.py           CleanupRunner: an async task that drives
│       │                                cleanup.run_async through SSE-backed callables
│       ├── runner_registry.py          holds at most one active CleanupRunner
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
│   │   │   ├── CleanupWizard/
│   │   │   │   ├── index.tsx           orchestrates the three steps
│   │   │   │   ├── ReviewStep.tsx
│   │   │   │   ├── ExecuteStep.tsx
│   │   │   │   ├── SummaryStep.tsx
│   │   │   │   └── CleanupWizardState.tsx    — React context (renamed from CleanJobContext to avoid name-clash with backend CleanupRunner)
│   │   │   ├── DiffTable.tsx
│   │   │   └── ui/                     shadcn components (copied-in)
│   │   ├── hooks/
│   │   │   ├── useScan.ts              TanStack Query wrapper
│   │   │   ├── useProviders.ts
│   │   │   ├── useSnapshots.ts
│   │   │   ├── useDiff.ts
│   │   │   ├── useSSE.ts               EventSource wrapper
│   │   │   └── useCleanupWizard.ts     wizard state machine (drives CleanupWizardState)
│   │   ├── api/
│   │   │   ├── client.ts               fetch helpers; base URL + error envelope
│   │   │   └── types.ts                GENERATED from FastAPI OpenAPI; do not edit by hand
│   │   └── lib/
│   │       └── format.ts               humanBytes, staleness — own tests, no cross-language assertions
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

### Scan, providers, recipe

```
GET  /api/scan?min_size=<str>&risk=<csv>&provider=<csv>
  Returns: Report (full JSON)
  No server-side caching. Scans are cheap (~0.4s on reference machine) and TanStack Query
  on the client handles any needed cache/stale-time behavior via `staleTime: 5000`.

GET  /api/providers
  Returns: ProviderInfo[]
    { name, description, risk, platforms, available: bool,
      required_binary: string | null, kind: "class" | "yaml",
      reason_if_unavailable: string | null }

POST /api/recipe
  body: { providers?: string[] }
  Returns: { script: string }  — always commented-out, from cleanup.build_script.
```

(`GET /api/scan/stream` was considered and dropped: a 400ms scan does not earn a streaming endpoint's code / test surface cost.)

### Cleanup

```
POST /api/clean/jobs
  body: { entry_ids: string[], yes_safe?: boolean, allow_dangerous?: boolean }
  Returns: { job_id: string }
  entry_ids are re-validated against a fresh scan at job start (no pre-baked "known ids" cache).
  If any id is unknown → 400 { error: { code: "unknown_entry", ... } }
  If a job is already active → 409 { error: { code: "job_in_progress", ... } }

GET  /api/clean/jobs/<id>/events
  SSE stream, heartbeat every 10s to survive idle connections during long prompt waits.

POST /api/clean/jobs/<id>/answer
  body: { entry_id: string, choice: "y" | "n" | "a" | "s" | "q" }
  Unblocks the server-side PromptChoice wait. 204 No Content.

POST /api/clean/jobs/<id>/confirm
  body: { confirmed: boolean }
  Unblocks the server-side Confirm wait. 204 No Content.

POST /api/clean/jobs/<id>/cancel
  Cancels the runner task, marks remaining entries skipped (reason: "cancelled"),
  emits a final `done` event, terminates. 204.
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

## Cleanup: core state machine + adapters

The cleanup logic is refactored so the state machine lives in one place and the sync / async entry points are thin adapters. This replaces the v1 monolithic `cleanup.run`.

```python
# src/diskdoctor/cleanup.py (post-refactor)

@dataclass
class PromptRequired:   entry: Entry
@dataclass
class ConfirmRequired:  approved: list[Entry]; total_bytes: int
@dataclass
class ExecuteStep:      entry: Entry; line: str   # one recipe line
@dataclass
class EntryResolved:    result: CleanResult

CleanupEvent = PromptRequired | ConfirmRequired | ExecuteStep | EntryResolved

def iter_cleanup_events(
    report: Report, opts: CleanupOpts
) -> Generator[CleanupEvent, Choice | bool | ShellResult, list[CleanResult]]:
    """Pure state machine. Never imports Shell, subprocess, Rich, or asyncio.

    Yields events; consumers send back the answer the event requested:
    - PromptRequired  → send Choice
    - ConfirmRequired → send bool
    - ExecuteStep     → send ShellResult (the adapter actually runs the shell)
    Returns the final list[CleanResult] via StopIteration.value.
    """
    ...
```

Both adapters are ~30 lines:

- **`cleanup.run(report, *, shell, prompt_choice, confirm, opts)` (sync, unchanged interface)** — drives the generator with sync calls to `shell.run`, `prompt_choice`, `confirm`. The CLI keeps using this; every v1 test keeps passing.
- **`cleanup.run_async(report, *, run_line, prompt_choice, confirm, opts)` (async)** — same driver, but `await`s the callables and uses `run_line: Callable[[str], Awaitable[ShellResult]]` supplied by the web layer (a thin wrapper over `subprocess_stream.py`). The web layer chooses this path so the event loop is never blocked by subprocesses.

Why this refactor is worth it: it eliminates the "two 150-line near-duplicates" failure mode, tests the state machine once (against scripted event sequences), and leaves the `Shell` port pure.

### CleanupRunner (web-side)

A `CleanupRunner` wraps one `cleanup.run_async` invocation:

- an outbound `asyncio.Queue[Event]` drained by the SSE route,
- a `dict[str, asyncio.Future[Choice]]` for pending per-entry answers,
- an `asyncio.Future[bool]` for the final confirm,
- an `asyncio.Task` for the runner itself (cancellable on SIGINT or `POST /cancel`).

The runner registry holds **at most one active runner**; a completed runner is immediately discarded. If the SSE connection drops mid-run, the user's recourse is to cancel (or let it finish) and then re-scan. No replay buffer, no resurrection window — the extra code didn't earn its keep for this rare failure mode.

## Frontend state

Three tiers, each with a clear owner:

- **Server cache → TanStack Query.** Hooks: `useScan`, `useProviders`, `useSnapshots`, `useDiff`. Stale times: scan 5s, providers 60s, snapshots on-mount. Mutations (snapshot create, recipe download) invalidate their key.
- **Wizard / runner → `CleanupWizardState`.** Lives under `<CleanupWizard/>`. Holds `{step, entries, selection, runnerId, events, error}`. Dies when the wizard unmounts. Never global. Names chosen deliberately to avoid clashing with the backend `CleanupRunner`.
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
- Binds `127.0.0.1:<port>`; port is `--port N` or a random free port if omitted.
- Opens the default browser via `webbrowser.open` unless `--no-browser`.
- Prints the URL and a "Ctrl-C to stop" line. `SIGINT` triggers uvicorn's graceful shutdown.
- **No `--dev` flag.** Developers run the Vite dev server separately on `http://localhost:5173` and Vite's built-in proxy forwards `/api/*` to the FastAPI port. No server-side toggle needed.
- Refuses to start with a clear error if the `web` extra isn't installed: `"Install with 'uv tool install \".[web]\" --force' to use the web UI."`
- If `--port N` is already bound → exit 1 with `"port N is in use; try --port 0 for a free one"`.

**Logging**: uvicorn's default access log is sufficient for v1. No custom log format, no structured logging. If v2 wants this, it's a one-liner (`logging.basicConfig(...)` at startup).

**SSE heartbeats**: every SSE route (currently just `/api/clean/jobs/<id>/events`) passes `ping=10` to `sse-starlette`'s `EventSourceResponse`. This emits a comment frame every 10s so idle intermediates don't drop the connection while the user is reading a `prompt` event before answering.

**Loading / empty / error states** (every data view):
- Loading → skeleton rows matching the final table geometry (8 placeholder rows).
- Empty (with filters) → "(no entries match your filters)" with one-click "clear filters" link.
- Empty (truly nothing) → "Nothing to reclaim. Your disk is in good shape." with timestamp.
- Provider unavailable → grey dot + tooltip reason. No red for "not installed".
- Scan in progress → sidebar's accent dot pulses while `useScan` is fetching; on response the rows appear together (scan is ~0.4s; a skeleton placeholder covers the gap).
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
| Shell hangs (e.g. `ollama list` wedged daemon) | `Shell.run(timeout=…)` in the relevant provider raises, provider marked unavailable | Row shown greyed; reason is the provider's own message |
| Clean job: shell command fails | CleanResult(status="error"); runner continues | Execute step marks ✗ on that entry, keeps going |
| Clean job: user cancels mid-execute | Runner task cancelled; remaining marked skipped; final `done` event emitted | Wizard jumps to Summary with partial results |
| Clean job: server killed mid-execute | SSE stream closes abruptly | Client shows "Connection lost — re-scan to see current state"; no resurrection / replay |
| Second concurrent `POST /api/clean/jobs` | 409 Conflict | Toast: "A cleanup is already in progress" |
| `entry_ids` contains unknown ids | 400 with `{code: "unknown_entry", ids: [...]}` | Toast pointing at the stale IDs; force-refresh the scan |
| Snapshot file malformed | 500 with error envelope | Toast on Snapshots page |

(Neither a 30s web-layer scan timeout nor an SSE replay buffer exists; both were considered and dropped as unnecessary complexity.)

## Testing

Existing Python v1 tests continue unchanged. New tests:

**Backend (pytest)**:
- `tests/test_cleanup_core.py` (≈15 tests) — `iter_cleanup_events` driven with scripted `.send()` inputs covers every path (y/n/a/s/q, yes-safe, DANGEROUS gate, final confirm, shell failure). This replaces the v1 `test_cleanup.py` execute-path coverage; the two adapters (`run`, `run_async`) keep just 1-2 tests each confirming they drive the core correctly.
- `tests/test_cleanup.py` (v1, unchanged) — still passes, because `cleanup.run` keeps the same signature and behavior.
- `tests/web/test_routes_scan.py` — `/api/scan` happy path, filter passthrough; `/api/providers`; `/api/recipe`.
- `tests/web/test_routes_clean.py` — full job lifecycle with `FakeShell`: `POST /jobs` → `GET /events` (async SSE consumer via `httpx-sse`) → `POST /answer` per prompt → `POST /confirm` → assert the stream of events plus the final `done.results` matches the synchronous `cleanup.run` for the same inputs.
- `tests/web/test_routes_history.py` — snapshot write / list / get + diff round-trip.
- `tests/web/test_runner_registry.py` — second concurrent job rejected with 409; cancelled runner releases the lock immediately.
- `tests/web/test_subprocess_stream.py` — helper yields stdout/stderr lines in arrival order; non-zero exit surfaces `ShellResult`; cancellation terminates the subprocess cleanly.
- `tests/web/test_host_header.py` — requests with mismatched `Host` header are rejected with 403; matching requests proceed.
- `tests/web/test_serve_cli.py` — `serve --help`; clear error when the `web` extra is missing; `--port` collision exits 1 with the expected message.

Coverage targets: cleanup core ≥95%, web routes ≥85%, runner registry ≥90%, subprocess_stream ≥90%.

**Frontend (Vitest)**:
- `web/tests/unit/format.test.ts` — table-driven cases for `humanBytes` (e.g. `1024 → "1.0K"`, `1_500_000_000 → "1.5G"`, `0 → "0B"`) and `staleness` (today / N d / N mo / N y) tested independently. Not cross-referenced against Python.
- `web/tests/unit/hooks/useSSE.test.ts` — EventSource mocked; status transitions; auto-reconnect on transient error.
- `web/tests/unit/hooks/useCleanupWizard.test.ts` — wizard state machine driven through scripted event sequences and reaches `done`.
- `web/tests/unit/components/RiskBadge.test.tsx`, `CacheTable.test.tsx` — rendering + interaction.

**Type sharing**: `web/src/api/types.ts` is **generated**, not hand-written. The build step runs `openapi-typescript http://127.0.0.1:<port>/openapi.json -o web/src/api/types.ts` (or reads FastAPI's exported schema from a build artefact) so the TypeScript types always match the FastAPI pydantic models. Zero drift; no hand-mirrored type hierarchy.

**Frontend (Playwright, smoke only)**:
- One test: launch `diskdoctor serve --port 8731 --no-browser`, hit the URL with Playwright, assert the scan view loads, trigger a preview-mode (dry-run) clean job end-to-end, assert the Summary step shows the expected counts. Uses a controlled `paths.yaml` via `DISKDOCTOR_PATHS_YAML` so the test is deterministic.

## Security considerations

- **Bind address**: `127.0.0.1` only. Refuse `0.0.0.0`. A future `--host` flag (not in v1) would require also setting a bearer token.
- **Host-header / DNS-rebinding protection** (REQUIRED): a middleware on `/api/*` rejects any request whose `Host` header isn't `127.0.0.1:<port>` or `localhost:<port>`. Without this, a malicious webpage can DNS-rebind the user's browser and POST destructive commands at `http://127.0.0.1:<port>`. With it, every cross-origin request is refused by the server before any handler runs.
- **CORS**: disabled entirely. In dev, the frontend runs under Vite at `http://localhost:5173` and proxies `/api/*` to the FastAPI server — the proxy makes the requests same-origin from the browser's perspective, so no CORS is ever needed. Production-built SPA is served by the same FastAPI, also same-origin.
- **Static / API routing order**: `app.mount("/api", api_router)` registered BEFORE `app.mount("/", StaticFiles(...))`. A SPA catch-all returns `index.html` for any GET that didn't match `/api/*` or a static file, so client-side routing works.
- **SSRF**: no server-side URL fetching; no user-supplied URLs anywhere.
- **Input validation**: pydantic on every POST body. `entry_ids` are validated at job-start against a fresh scan (not a cached set); unknown IDs → 400.
- **Shell injection**: the web layer does not construct shell strings. `cleanup.iter_cleanup_events` yields `ExecuteStep(entry, line)` where `line` was already constructed by the provider in v1 using `shlex.quote`. The web adapter splits via `shlex.split` (same as CLI) before handing to `asyncio.create_subprocess_exec`.
- **Concurrency**: one runner at a time; scan is idempotent and parallel-safe with a running clean.
- **Shutdown**: `SIGINT` triggers uvicorn's graceful shutdown; the active runner task is cancelled (propagating to its in-flight subprocess via `terminate()`); the SSE stream emits a final `error: shutdown` event.
- **Port collision**: if `--port N` is already bound, uvicorn raises `OSError`; the `serve` command catches it and exits 1 with `"port N is in use; try --port 0 for a free one"`.

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

- **Reuse Python domain, don't re-model on the wire.** `Report.to_json()` is the single source of truth — used by `--json`, snapshots, and the web. TypeScript types on the client are **generated from FastAPI's OpenAPI** via `openapi-typescript`; no hand-mirrored hierarchy, zero drift risk.
- **Lift the cleanup state machine into a pure generator** (`iter_cleanup_events`). Both `cleanup.run` (sync, CLI) and `cleanup.run_async` (async, web) are ≈30-line adapters over the core. Tested once against scripted event sequences. Earlier drafts duplicated ~150 lines of near-identical logic between sync and async paths — rejected.
- **`Shell` stays sync-only and unchanged.** An earlier draft extended `Shell.run` with an async `stream` callback kwarg; rejected as a DIP violation (the feature would be consumed by one caller — the web subprocess stream — but bolted onto every Shell user). The web layer uses its own async subprocess helper (`web/subprocess_stream.py`) and never touches `Shell`.
- **SSE over WebSockets.** One-way data flow today. If cancel-mid-shell-command ever matters, WebSockets replace SSE in a single route file. SSE responses carry a 10s heartbeat so idle waits don't drop.
- **Host-header / DNS-rebinding middleware** on `/api/*`. Without it, `127.0.0.1`-only binding isn't sufficient for destructive endpoints — a malicious webpage could DNS-rebind the user's browser.
- **No server-side scan cache and no completed-job replay buffer.** TanStack Query handles any useful caching on the client with `staleTime: 5000`. If the SSE stream drops mid-job, the user re-scans to observe current state; rare scenario, not worth the code.
- **No streaming scan endpoint.** Scan is ~0.4s on the reference machine; a second `/api/scan/stream` endpoint doubles the code / test surface for a negligible UX win. Dropped.
- **Monorepo, no separate npm package.** diskdoctor is one app; shipping two version-locked releases is needless overhead. Users install with one `uv tool install .` and never touch Node.
- **State lives where it belongs.** Server cache in TanStack Query; wizard state scoped to the wizard tree; UI state in the URL. No global store.
- **Palette via CSS variables.** Tailwind v4 lets us keep CSS-variable-driven theming without fighting the utility-class model. Future light theme is a variable-swap, not a rewrite.

## Changes from v1 (self-review)

Architectural fixes:

- **Dropped `Shell.run(stream=…)` extension.** Replaced with a web-only `subprocess_stream.py` helper that uses `asyncio.create_subprocess_exec` directly. The `Shell` port stays pristine sync-only.
- **Lifted cleanup state machine into `iter_cleanup_events` generator.** Both sync `cleanup.run` and new async `cleanup.run_async` are thin adapters. Eliminates the "two 150-line near-duplicates" risk v1 glossed over.
- **Host-header / DNS-rebinding middleware added** as a hard requirement on `/api/*` — previously implicit.
- **Explicit static / API routing order**: `/api` mounted first; SPA catch-all returns `index.html` for non-matching GETs.
- **SSE heartbeats** (`ping=10`) required on long-lived streams to survive idle prompt waits.

Over-engineering removed:

- **Dropped `GET /api/scan/stream`** — scan is 0.4s; streaming endpoint was not earning its cost.
- **Dropped server-side scan cache** (5s TTL + invalidation). TanStack Query's client-side `staleTime` handles this. One fewer cache layer to reason about.
- **Dropped 60-second completed-job replay buffer.** Real disconnect recovery: user re-scans. Simpler.
- **Dropped `diskdoctor serve --dev` + CORS config.** Vite's proxy handles dev mode transparently; the flag was inventing complexity.
- **Merged `routes_recipe.py` into `routes_scan.py`** — one endpoint didn't earn its own module.
- **Dropped 30s web-layer scan timeout.** Per-provider timeouts are `Shell.run(timeout=…)`'s job already (added in v1).

DRY / testability:

- **`web/src/api/types.ts` is generated** from FastAPI's OpenAPI (`openapi-typescript`). Removed hand-mirrored type hierarchy.
- **`format.ts` tests are independent**, not cross-referenced against `rendering.py`. Cross-language "they match" assertions were brittle.

Naming:

- **Backend `CleanJob` → `CleanupRunner`**; **frontend `CleanJobContext` → `CleanupWizardState`**; **`useCleanJob` → `useCleanupWizard`**. Three distinct concerns, three distinct names.

Nits:

- Fixed line 74 typo (`Provider.run` → `cleanup.run`) — moot after the Shell-kwarg decision reverted.
- Added port-collision handling, logging default, clarified `--no-browser` interaction.
