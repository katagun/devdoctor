# Web UI guide

The web UI is the same engine behind a local dashboard. Nothing leaves your
machine: the server binds loopback and serves the SPA plus a JSON API.

## Launch

```bash
# Install with the web extra (once)
uv tool install '.[web]' --force

# Launch (opens a browser tab at a random free port)
devdoctor serve

# Pin the port, or skip the auto-open tab
devdoctor serve --port 8731 --no-browser
```

`--port 0` (the default) picks a random free port; `--port N` binds `N`.

## Pages

- **Disk** — the scan as charts and tables, with live progress while a scan
  runs (providers finished, bytes found so far, what is still running).
- **Memory** — RAM pressure state plus top live consumers by real RSS, with
  safe fixes (quit the app, stop the container) instead of raw `kill`.
- **Cleanup wizard** — the plan, per-entry prompts, and live output,
  step by step: the GUI form of `clean --execute`.
- **History** — past cleanup runs, shared with the CLI's `history` log.
- **Snapshots** — capture and diff disk states, shared with the CLI's
  `snapshot` / `diff` store.
- **Settings** — app preferences (also `GET` / `PATCH /api/settings`).

## API (all under `/api`, loopback only)

Disk:

- `GET /api/health` — liveness probe (the desktop shell waits on this).
- `GET /api/scan` and `GET /api/disk/scan` — run a scan, JSON report.
- `GET /api/scan/progress` — server-sent events: per-provider progress.
- `GET /api/providers` — registered providers and availability.
- `POST /api/recipe` — build the commented-out cleanup script.
- `GET /api/disk-usage`, `GET /api/snapshots`, `POST /api/snapshots`,
  `GET /api/snapshots/{name}`, `GET /api/diff`, `GET /api/history`,
  `GET /api/dashboard/disk-summary`.

Cleanup jobs (the wizard backend):

- `POST /api/clean/jobs` — start a cleanup job.
- `GET /api/clean/jobs/{job_id}/events` — SSE stream of plan, prompts,
  per-entry results.
- `POST /api/clean/jobs/{job_id}/answer` — answer a per-entry prompt.
- `POST /api/clean/jobs/{job_id}/confirm` — final confirmation.
- `POST /api/clean/jobs/{job_id}/cancel` — cancel the job.

Memory: `GET /api/memory`, `/api/memory/history`, `/api/memory/snapshots*`,
`/api/memory/sources`, `/api/memory/providers`, `/api/memory/workloads`,
`POST /api/memory/plan`, `POST /api/memory/actions`.

## Developing the UI

```bash
# One-time: install the SPA dependencies
cd web && bun install --frozen-lockfile && cd ..

# Terminal 1: FastAPI (this repo's backend)
uv run devdoctor serve --port 8731 --no-browser

# Terminal 2: Vite with HMR (proxies /api to 8731)
cd web && bun run dev
```

Open http://localhost:5173. For a production-style run, `./scripts/deploy.sh`
builds the SPA, drops the stale wheel (`uv cache clean devdoctor`), and
reinstalls with the bundle included — run the steps in that order, or just
run the script.
