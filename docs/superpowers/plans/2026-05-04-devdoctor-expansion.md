# DevDoctor Expansion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the product from disk cleanup into a local developer workstation resource manager named **DevDoctor**, while preserving the existing diskdoctor disk scan, cleanup, snapshot, history, and provider functionality.

**Core feedback captured:** Rename the visible product to DevDoctor now. Do a small preparatory refactor first, but do not force memory into the existing disk `Entry` / `Provider` / cleanup recipe model. Add memory as a sibling domain with live telemetry, advisory suggestions, workload planning, and later optional browser tab management.

**Architecture:** Keep the existing disk domain stable. Add a new memory domain beside it: memory collectors gather live system/app/process data, an advisor turns telemetry into ranked suggestions, and optional action adapters execute structured memory actions with confirmation. Browser tab-level management is treated as an optional extension bridge because OS process telemetry alone usually cannot map memory accurately to individual tabs.

**Tech Stack:** Existing Python 3.12 + FastAPI + React/Vite stack. Use stdlib/macOS command-line telemetry first for a local-only MVP. Introduce optional browser extension surfaces only after the memory report/advisor shape is stable.

**Reference docs:**
- Existing disk design: `docs/superpowers/specs/2026-04-18-diskdoctor-design.md`
- Existing web design: `docs/superpowers/specs/2026-04-18-web-ui-design.md`

---

## Decisions

- [x] **Product name:** Use **DevDoctor** for visible app branding.
- [x] **Package name:** Keep `diskdoctor` as the Python package and CLI entry point during the initial expansion.
- [x] **Compatibility:** Keep `/`, `/api/scan`, cleanup jobs, snapshots, and history working as they do today.
- [x] **Navigation:** Make disk an explicit domain in the UI, then add memory as a second domain.
- [x] **Domain model:** Do not generalize `Entry` or `Provider` before memory exists. Disk entries are cleanup candidates; memory consumers are live, volatile resource observations.
- [x] **Memory posture:** Start read-only, then add suggestions, then add confirmed actions.
- [x] **Browser posture:** Treat per-tab management as a later optional browser extension bridge, not as a Python-only process scraping feature.
- [x] **Persistence posture:** Add a storage abstraction before implementing memory history/snapshots. Keep filesystem storage as the default compatible backend, then add SQLite as an opt-in backend.
- [x] **Settings posture:** Split browser-local preferences from server-side app settings. Storage backend selection is a server-side setting exposed in the Settings page, not just a frontend `localStorage` preference.
- [x] **Migration posture:** Do not destructively migrate existing disk snapshots/audit logs. SQLite adoption should import or preserve existing filesystem data and make backend switching explicit.
- [x] **Memory provider posture:** Manage memory process categories as selectable providers, parallel to disk providers. Providers default to enabled, can be disabled individually, and include browsers, Electron apps such as Slack, Docker, local LLM runtimes, native apps, and other processes.

---

## Phase 0: Brand and Scope Guardrails

**Goal:** Rename the visible product without creating a broad module/package rename.

**Files likely touched:**
- `README.md`
- `web/src/components/Sidebar.tsx`
- `web/src/App.tsx`
- `web/src/pages/*`
- `src/diskdoctor/cli.py`
- tests that assert visible labels

- [x] **Step 1: Add an app branding constant**

Create a small frontend constant such as `web/src/lib/brand.ts`:

```ts
export const APP_NAME = "DevDoctor";
export const LEGACY_APP_NAME = "diskdoctor";
```

Use the visible `APP_NAME` in the sidebar/header. Leave backend package/module names unchanged.

- [x] **Step 2: Update visible UI copy**

Change visible product text from `diskdoctor` to `DevDoctor`.

Keep technical labels that refer to the current CLI/package only where they are intentionally compatibility-related.

- [x] **Step 3: Update README positioning**

Describe the project as DevDoctor, currently shipped through the `diskdoctor` CLI/package for compatibility.

Suggested wording:

```md
# DevDoctor

DevDoctor is a local developer workstation resource manager. Today it includes disk cleanup for model caches, Docker artifacts, package caches, browser data, and other reclaimable local state. Memory pressure management is planned next.

The current installable Python package and CLI remain named `diskdoctor` during the transition.
```

- [x] **Step 4: Verify**

Run:

```bash
uv run pytest -q
cd web && npm run test
cd web && npm run typecheck
```

---

## Phase 1: Make Disk Explicit Without Breaking Compatibility

**Goal:** Create room for memory by making disk a first-class domain in the UI and API naming, while keeping old routes intact.

**Files likely touched:**
- `web/src/App.tsx`
- `web/src/pages/Scan.tsx`
- `web/src/components/Sidebar.tsx`
- `web/src/hooks/useScan.ts`
- `src/diskdoctor/web/routes_scan.py`
- route tests and frontend navigation tests

- [x] **Step 1: Add `/disk` as the primary disk route**

Keep `/` rendering the same disk page as a compatibility/default route.

Recommended frontend route shape:

```tsx
<Route index element={<DiskScan />} />
<Route path="disk" element={<DiskScan />} />
```

- [x] **Step 2: Rename page/component symbols conservatively**

Rename `Scan.tsx` to `DiskScan.tsx` if the churn is small. If tests or imports become noisy, keep the filename and only update route/sidebar labels.

- [x] **Step 3: Add disk API aliases only if useful**

Optional alias:

```http
GET /api/disk/scan
```

It should call the same implementation as existing:

```http
GET /api/scan
```

Do not remove `/api/scan`.

- [x] **Step 4: Keep disk snapshots unchanged**

Do not rename snapshot schema fields yet. Existing snapshots are disk reports and should remain readable without migration.

- [x] **Step 5: Verify old and new paths**

Backend tests should cover both `/api/scan` and any new `/api/disk/scan` alias. Frontend tests should cover both `/` and `/disk` routing if the router setup supports that easily.

---

## Phase 2: Add a Read-Only Memory Domain

**Goal:** Add live memory visibility as a sibling to disk, not a refactor of disk providers.

**New files likely:**
- `src/diskdoctor/memory/__init__.py`
- `src/diskdoctor/memory/types.py`
- `src/diskdoctor/memory/collectors/__init__.py`
- `src/diskdoctor/memory/collectors/system.py`
- `src/diskdoctor/memory/collectors/processes.py`
- `src/diskdoctor/memory/discovery.py`
- `src/diskdoctor/web/routes_memory.py`
- `tests/memory/test_*.py`
- `tests/web/test_routes_memory.py`
- `web/src/pages/Memory.tsx`
- `web/src/hooks/useMemory.ts`

- [x] **Step 1: Define memory-specific types**

Do not reuse disk `Entry`.

Suggested initial shape:

```python
@dataclass(frozen=True)
class SystemMemory:
    total_bytes: int
    available_bytes: int
    used_bytes: int
    swap_used_bytes: int | None
    compressed_bytes: int | None
    pressure: Literal["ok", "warn", "critical", "unknown"]

@dataclass(frozen=True)
class MemoryConsumer:
    id: str
    pid: int | None
    parent_pid: int | None
    name: str
    kind: Literal["app", "process", "browser", "electron", "docker", "llm", "other"]
    rss_bytes: int
    private_bytes: int | None
    command: str | None
    children: list["MemoryConsumer"]

@dataclass(frozen=True)
class MemoryReport:
    scanned_at: datetime
    hostname: str
    platform: str
    system: SystemMemory
    consumers: list[MemoryConsumer]
```

- [x] **Step 2: Implement macOS system memory collection**

Use a parser behind tests. Likely sources:

- `vm_stat`
- `sysctl hw.memsize`
- `memory_pressure` where available

Keep parser functions pure and unit-tested with fixture output.

- [x] **Step 3: Implement process collection**

Start with command-line process data. Group obvious app families:

- browsers: Firefox, Chrome, Arc, Safari, Chromium
- containers: Docker Desktop, `com.docker.*`
- local LLM: Ollama, LM Studio, llama.cpp-style processes
- developer tools: VS Code/Cursor/JetBrains terminals as lower-priority grouping

- [x] **Step 4: Add `/api/memory`**

Wire `routes_memory.py` into `build_app()` next to the existing route includes.

Initial response should be the read-only `MemoryReport`.

- [x] **Step 5: Add `/memory` page**

Initial page should show:

- memory pressure strip
- total/available/swap/compressed stats
- top consumers grouped by kind
- refresh cadence around 5-10 seconds while page is mounted

- [x] **Step 6: Verify**

Run backend, frontend, and type checks:

```bash
uv run pytest -q
cd web && npm run test
cd web && npm run typecheck
```

---

## Phase 3: Add Advisory Suggestions

**Goal:** Turn memory observations into ranked, explainable suggestions without executing anything.

**New files likely:**
- `src/diskdoctor/memory/advisor.py`
- `tests/memory/test_advisor.py`
- `web/src/components/MemorySuggestions.tsx`

- [x] **Step 1: Define suggestion/action types**

Suggested shape:

```python
@dataclass(frozen=True)
class MemoryAction:
    id: str
    kind: Literal["discard_tabs", "stop_container", "stop_service", "quit_app", "terminate_process"]
    label: str
    target_id: str
    estimated_bytes: int | None
    risk: Literal["safe", "reclaimable", "dangerous"]

@dataclass(frozen=True)
class MemorySuggestion:
    id: str
    title: str
    reason: str
    estimated_bytes: int | None
    confidence: Literal["low", "medium", "high"]
    actions: list[MemoryAction]
```

- [x] **Step 2: Add deterministic advisor rules**

Initial rules:

- browser is over threshold and memory pressure is high: suggest tab discard workflow, not browser quit
- Docker is high and no active containers are detected: suggest stopping Docker Desktop
- Ollama/LM Studio is high and no current local model workload is planned: suggest stopping model server or unloading model
- process termination is always last resort and marked dangerous

- [x] **Step 3: Surface suggestions on the memory page**

Show suggestions above the process list. Keep them advisory only in this phase.

---

## Phase 4: Add Server-Side Settings and Storage Abstraction

**Goal:** Make persistence configurable without changing existing disk behavior. This is the foundation for memory history, memory snapshots, and future app-wide records.

**New files likely:**
- `src/diskdoctor/config.py`
- `src/diskdoctor/storage/__init__.py`
- `src/diskdoctor/storage/base.py`
- `src/diskdoctor/storage/filesystem.py`
- `src/diskdoctor/web/routes_settings.py`
- `tests/test_config.py`
- `tests/storage/test_filesystem_storage.py`
- `tests/web/test_routes_settings.py`
- `web/src/hooks/useAppSettings.ts`

- [x] **Step 1: Define server-side app settings**

Keep existing frontend preferences in `localStorage`, but introduce server-backed app settings for settings that affect backend behavior.

Initial app settings:

```python
StorageBackendName = Literal["filesystem", "sqlite"]

@dataclass(frozen=True)
class AppSettings:
    storage_backend: StorageBackendName
    data_dir: Path
    sqlite_path: Path
```

Recommended config location:

```text
$XDG_CONFIG_HOME/devdoctor/config.json
```

Fallback to `~/.config/devdoctor/config.json`. Keep `$XDG_DATA_HOME/diskdoctor` / `~/.local/share/diskdoctor` readable for existing data during the transition.

- [x] **Step 2: Add `/api/settings`**

Expose:

```http
GET /api/settings
PATCH /api/settings
```

The Settings page should show storage backend, data directory, SQLite file path, and whether a restart is needed. For the first implementation, allow choosing the backend in UI but keep the switch conservative:

- persist the selected backend server-side
- validate SQLite can be opened before saving `sqlite`
- never delete filesystem snapshots/audit logs
- show a warning if switching backends may hide records that only exist in the other backend

- [x] **Step 3: Define a storage backend protocol**

Start with the methods needed by current disk functionality. Do not add memory persistence yet.

```python
class StorageBackend(Protocol):
    def write_disk_snapshot(self, report: Report) -> StoredSnapshot: ...
    def list_disk_snapshots(self, *, limit: int | None, kind: SnapshotKind | None) -> list[StoredSnapshotMeta]: ...
    def load_disk_snapshot(self, name: str) -> Report: ...
    def prune_auto_disk_snapshots(self, *, keep: int) -> list[str]: ...
    def append_audit_event(self, event: Mapping[str, object]) -> None: ...
    def read_audit_events(self, *, limit: int | None) -> list[dict[str, object]]: ...
```

- [x] **Step 4: Wrap current filesystem behavior**

Implement `FilesystemStorage` as a thin adapter around the existing JSON snapshot files and JSONL audit log. Existing routes should call storage methods, but behavior and file formats should remain unchanged.

- [x] **Step 5: Wire storage through the app**

Add a storage factory to FastAPI app state:

```python
app.state.storage = build_storage(load_app_settings())
```

Update disk routes and cleanup audit writing to use `request.app.state.storage` or an injected storage object. Keep CLI commands using the same storage abstraction where practical.

- [x] **Step 6: Verify compatibility**

Run existing disk snapshot/history/cleanup tests unchanged. Add tests proving filesystem backend still writes the same JSON files and JSONL audit entries.

---

## Phase 5: Add SQLite Storage Backend

**Goal:** Add SQLite as an opt-in persistence backend for structured history, future memory observations, and fast time-window queries.

**New files likely:**
- `src/diskdoctor/storage/sqlite.py`
- `src/diskdoctor/storage/migrations.py`
- `tests/storage/test_sqlite_storage.py`

- [x] **Step 1: Add migration runner**

Use stdlib `sqlite3`. Keep migrations explicit and testable.

Initial tables:

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE disk_snapshots (
  name TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  scanned_at TEXT NOT NULL,
  hostname TEXT NOT NULL,
  platform TEXT NOT NULL,
  note TEXT,
  total_bytes INTEGER NOT NULL,
  duration_ms INTEGER,
  report_json TEXT NOT NULL
);

CREATE INDEX idx_disk_snapshots_kind_scanned_at
  ON disk_snapshots(kind, scanned_at DESC);

CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE INDEX idx_audit_events_at ON audit_events(at DESC);
```

- [x] **Step 2: Implement `SQLiteStorage` for existing disk records**

Store full report JSON for compatibility, plus indexed metadata for list/diff/history views.

- [x] **Step 3: Add filesystem import**

When the user selects SQLite, offer or run a safe import:

- import existing disk snapshots into `disk_snapshots`
- import existing audit JSONL events into `audit_events`
- skip duplicates by stable snapshot name / audit event identity
- leave source files untouched

- [x] **Step 4: Add backend selection tests**

Cover:

- filesystem backend remains default
- SQLite backend initializes schema
- invalid SQLite path fails settings validation
- switching backend does not delete data
- existing snapshots are visible after import

---

## Phase 6: Add Memory History, Snapshots, and Providers

**Goal:** Add the memory equivalents of history/snapshots/providers in a memory-native shape.

**Decision:** Do not copy the disk page model directly. Memory uses:

- **history**: time-series observations and pressure episodes
- **snapshots**: named memory checkpoints for before/after comparison
- **providers**: selectable memory consumer categories such as browsers, Electron apps, Docker, local LLM runtimes, native apps, and other processes
- **sources**: compatibility/readiness metadata for underlying telemetry integrations such as system process table, browser bridge, Docker, and local LLM runtime probes

**New files likely:**
- `src/diskdoctor/memory/history.py`
- `src/diskdoctor/memory/snapshots.py`
- `src/diskdoctor/memory/providers.py`
- `tests/memory/test_history.py`
- `tests/memory/test_snapshots.py`
- `tests/memory/test_sources.py`
- `tests/memory/test_providers.py`
- `web/src/pages/MemoryHistory.tsx` or a tab inside `Memory.tsx`
- `web/src/pages/MemorySnapshots.tsx` or a tab inside `Memory.tsx`

- [x] **Step 1: Extend storage protocol for memory observations**

Suggested methods:

```python
def write_memory_observation(self, report: MemoryReport, suggestions: list[MemorySuggestion]) -> str: ...
def list_memory_observations(self, *, since: datetime | None, limit: int) -> list[MemoryObservationMeta]: ...
def load_memory_observation(self, observation_id: str) -> MemoryReport: ...
def create_memory_snapshot(self, report: MemoryReport, *, note: str | None) -> MemorySnapshotMeta: ...
def list_memory_snapshots(self, *, limit: int | None) -> list[MemorySnapshotMeta]: ...
```

Filesystem backend can use JSONL or JSON files for parity, but SQLite should be the preferred backend for memory history.

- [x] **Step 2: Add SQLite memory tables**

Start pragmatic: store full report/suggestions JSON plus indexed summary fields.

```sql
CREATE TABLE memory_observations (
  id TEXT PRIMARY KEY,
  scanned_at TEXT NOT NULL,
  pressure TEXT NOT NULL,
  total_bytes INTEGER NOT NULL,
  available_bytes INTEGER NOT NULL,
  used_bytes INTEGER NOT NULL,
  swap_used_bytes INTEGER,
  compressed_bytes INTEGER,
  top_consumer_name TEXT,
  top_consumer_kind TEXT,
  top_consumer_rss_bytes INTEGER,
  report_json TEXT NOT NULL,
  suggestions_json TEXT NOT NULL
);

CREATE INDEX idx_memory_observations_scanned_at
  ON memory_observations(scanned_at DESC);

CREATE INDEX idx_memory_observations_pressure_scanned_at
  ON memory_observations(pressure, scanned_at DESC);

CREATE TABLE memory_snapshots (
  name TEXT PRIMARY KEY,
  observation_id TEXT,
  created_at TEXT NOT NULL,
  note TEXT,
  report_json TEXT NOT NULL
);
```

- [x] **Step 3: Record memory observations**

When `/api/memory` is requested, optionally record observations with a rate limit. Keep the first version simple:

- record at most once per configured cadence while `/memory` is open
- always record pressure transitions
- retain only a bounded window by default

- [x] **Step 4: Add memory history view**

Show:

- pressure over time
- swap/compressed trend
- top consumers per observation
- suggestions emitted during pressure episodes

- [x] **Step 5: Add memory snapshots**

Allow named memory checkpoints and before/after diffs. Diff fields:

- available/used/swap/compressed delta
- top consumer deltas by stable process/app/source identity where possible
- suggestions gained/lost between snapshots

- [x] **Step 6: Add memory providers view**

Use the disk provider interaction model: all providers are enabled by default, individual providers can be disabled, and the disabled set is stored as a browser-local preference. Provider selection filters live memory consumers, suggestions, workload planning, and memory snapshots.

Initial providers:

- browsers
- Electron apps, including Slack and similar resource-heavy app shells
- Docker
- local LLM runtimes
- native apps
- other processes

---

## Phase 7: Add Workload Planning / Binpacking

**Goal:** Answer “Can I do this with my current memory headroom?” and “What should I free first?”

**New files likely:**
- `src/diskdoctor/memory/workloads.py`
- `src/diskdoctor/memory/planner.py`
- `tests/memory/test_planner.py`
- `web/src/components/WorkloadPlanner.tsx`

- [x] **Step 1: Define workload inputs**

Support explicit workload cards first:

- run local LLM model, user-entered estimated memory
- keep Docker active
- keep browser profile active
- reserve memory for IDE/build/test run

- [x] **Step 2: Add fit calculation**

Use conservative headroom:

```text
available - os_reserve - user_safety_margin
```

Represent estimates honestly. macOS memory compression and file cache mean these are planning signals, not exact guarantees.

- [x] **Step 3: Generate free-up plans**

Use ranked suggestions from Phase 3 as candidate actions. Prefer lower-risk/lower-disruption actions first.

- [x] **Step 4: UI**

Add a planner panel to `/memory`:

- choose workload
- show current fit / no-fit
- show recommended actions to create enough headroom

---

## Phase 8: Add Confirmed Memory Actions

**Goal:** Execute selected memory actions through explicit confirmation, similar in spirit to disk cleanup but not implemented as disk cleanup recipes.

**New files likely:**
- `src/diskdoctor/memory/actions.py`
- `src/diskdoctor/web/routes_memory_actions.py`
- `tests/memory/test_actions.py`

- [ ] **Step 1: Implement low-risk actions first**

Initial candidates:

- stop idle Docker containers
- stop Docker Desktop
- stop Ollama service/process with confirmation
- quit a known app via AppleScript or process signal only with clear confirmation

- [ ] **Step 2: Add an action safety model**

Do not reuse disk `Risk` blindly if memory needs more nuance. At minimum, keep:

- safe: reversible/unloads idle resource
- reclaimable: interrupts a service but does not destroy state
- dangerous: can lose unsaved state

- [ ] **Step 3: Stream action progress if needed**

Reuse existing SSE patterns from cleanup jobs only if actions become long-running.

---

## Phase 9: Optional Browser Extension Bridge

**Goal:** Provide reliable tab-level visibility/actions for Firefox and Chromium-based browsers.

**Why optional:** Python process telemetry can identify browser memory at app/process level, but browser APIs are needed for reliable tab titles, URLs, tab active/discarded state, and tab discard actions.

- [ ] **Step 1: Design local bridge protocol**

The extension should send tab metadata to the local DevDoctor server only when explicitly enabled by the user.

Suggested local endpoints:

```http
POST /api/browser-bridge/snapshot
POST /api/browser-bridge/action-result
```

- [ ] **Step 2: Start read-only**

Collect:

- browser family/profile
- window id
- tab id
- title/url/domain
- active/discarded/audible/pinned state
- last access time if available
- browser-reported process/memory fields where available

- [ ] **Step 3: Add discard actions**

Use browser-supported `tabs.discard()` APIs. Respect restrictions: active tabs and some unload-protected pages cannot be discarded.

- [ ] **Step 4: Keep privacy local**

No telemetry, no remote sync, no unsolicited network calls. Tab URLs/titles stay local.

---

## Non-Goals for This Refactor

- [ ] Do not rename `src/diskdoctor/` yet.
- [ ] Do not remove the `diskdoctor` CLI yet.
- [ ] Do not destructively migrate existing snapshot files.
- [ ] Do not build a background daemon in the first memory pass.
- [ ] Do not make the disk provider system generic before memory has proven its own model.
- [ ] Do not promise exact per-tab memory from Python-only process inspection.

---

## Suggested Implementation Order

1. Phase 0: visible DevDoctor rename.
2. Phase 1: `/disk` route and disk naming guardrails.
3. Phase 2: read-only `/memory` report.
4. Phase 3: suggestions.
5. Phase 4: server-side settings and storage abstraction.
6. Phase 5: SQLite storage backend and safe import.
7. Phase 6: memory history, memory snapshots, and memory providers.
8. Phase 7: workload planner.
9. Phase 8: confirmed memory actions.
10. Phase 9: optional browser extension bridge.
