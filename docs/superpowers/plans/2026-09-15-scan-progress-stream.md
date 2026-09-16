# Streamed Scan Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show which providers are pending, running and done — with entries and bytes found so far — while a web scan runs, over a server-sent-events side channel that never touches the scan's own data path.

**Architecture:** `discovery.scan` gains an optional `on_progress` callback that emits `ScanStarted` / `ProviderStarted` / `ProviderFinished` events from the scan threads. A thread-safe `ScanProgressHub` on `app.state` turns those events into a versioned snapshot; `GET /api/scan/progress` streams the snapshot as SSE whenever the version changes. The Disk page opens the stream only while its scan query is fetching and renders one progress line; the Dashboard appends the provider count to its loading label.

**Tech Stack:** Python 3.12, FastAPI, sse-starlette, pytest (asyncio auto mode), httpx-sse; React 18, TanStack Query, Vitest + Testing Library, Playwright 1.62, Bun 1.4.

**Spec:** `docs/superpowers/specs/2026-09-15-scan-progress-stream-design.md`

## Global Constraints

- Progress is decoration: a missing, late or broken stream never affects the scan or the page's data (spec §2.4). No change to the request or response of `GET /api/scan`.
- The callback is invoked through one helper that catches every exception, logs it once at warning level with the event name, and continues (spec §3).
- `ProviderFinished.timing` is what `_discover_one` computed, before reconciliation and containment (spec §3).
- Only `/api/scan` and `/api/disk/scan` report progress; the cleanup wizard's containment-off scan and the recipe route do not (spec §5).
- Events with a `scan_id` older than the hub's current one are ignored (spec §4).
- The stream ends only after a transition into `done` it observed itself; an initial `done` or `idle` snapshot keeps it open (spec §5).
- Snapshot JSON field names are exactly: `scan_id, status, started_at, total, done, running, entries, bytes, providers[{name, status, duration_ms, entries, bytes}]` (spec §4).
- Every test is written before the code it covers and watched fail (spec §8).
- Python: ruff (line length 100), `mypy --strict`; commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Web: `bun run lint`, `bun run typecheck`, `bun run test`, `bun run test:e2e` must pass; `bun run build` rewrites the tracked placeholder `src/devdoctor/web/_static/dist/index.html` — run `git checkout -- src/devdoctor/web/_static/dist/index.html` before committing.
- Working directory for web commands: `web/`. Python commands run from the repo root with `uv run --extra dev --extra web ...`.

---

## File structure

| File | Responsibility |
|---|---|
| `src/devdoctor/discovery.py` (modify) | Progress event dataclasses, `ScanProgressCallback`, `_notify`, `on_progress` keyword on `scan()`, events from `_discover_one` |
| `src/devdoctor/web/scan_progress.py` (create) | `ProviderProgress`, `ScanProgressSnapshot` (+ `to_json`), `ScanProgressHub` |
| `src/devdoctor/web/routes_scan.py` (modify) | Pass `hub.observer()` to `discovery.scan` in `/api/scan`; `GET /api/scan/progress` SSE route |
| `src/devdoctor/web/app.py` (modify) | `app.state.scan_progress = ScanProgressHub()` |
| `web/src/lib/scanProgress.ts` (create) | Snapshot TypeScript types, `formatScanProgress` |
| `web/src/hooks/useScanProgress.ts` (create) | EventSource subscription while active |
| `web/src/components/ScanProgressLine.tsx` (create) | Progress line (+ optional bar) with the countdown |
| `web/src/pages/Scan.tsx`, `web/src/pages/Dashboard.tsx` (modify) | Wire the hook and the line |
| `tests/test_discovery.py`, `tests/web/test_scan_progress.py`, `tests/web/test_routes_scan.py` | pytest |
| `web/tests/unit/scanProgress.test.ts`, `useScanProgress.test.ts`, `ScanProgressLine.test.tsx` | vitest |
| `web/tests/e2e/progress.spec.ts` (create) | Playwright |
| `CHANGELOG.md`, `README.md` | Docs |

---

### Task 1: Discovery progress callback

**Files:**
- Modify: `src/devdoctor/discovery.py` (imports at top; `_discover_one` ~line 120; `scan()` ~line 169)
- Test: `tests/test_discovery.py` (append)

**Interfaces:**
- Consumes: existing `_discover_one(p) -> _ProviderResult`, `ProviderTiming`.
- Produces (used by Tasks 2–3):
  ```python
  @dataclass(frozen=True) class ScanStarted: providers: tuple[str, ...]
  @dataclass(frozen=True) class ProviderStarted: name: str
  @dataclass(frozen=True) class ProviderFinished: timing: ProviderTiming
  ScanProgressEvent = ScanStarted | ProviderStarted | ProviderFinished
  ScanProgressCallback = Callable[[ScanProgressEvent], None]
  def scan(providers, filters, now, *, contain=True, on_progress: ScanProgressCallback | None = None) -> Report
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_discovery.py` (it already imports `discovery`, `datetime`, `UTC`, `ScanFilters`, `FakeShell`, and defines `_Stub`, `_FakeProvider`, `_fe`, `_Raising`):

```python
import threading


def _collect_progress() -> tuple[list[discovery.ScanProgressEvent], discovery.ScanProgressCallback]:
    """A thread-safe sink for progress events (providers report from worker threads)."""
    events: list[discovery.ScanProgressEvent] = []
    lock = threading.Lock()

    def on_progress(event: discovery.ScanProgressEvent) -> None:
        with lock:
            events.append(event)

    return events, on_progress


def _index_of(events, predicate) -> int:
    return next(i for i, e in enumerate(events) if predicate(e))


def test_scan_reports_progress_per_available_provider() -> None:
    events, on_progress = _collect_progress()
    a = _FakeProvider(name="a", entries=[_fe(provider="a", size=100), _fe(provider="a", size=200)])
    off = _Stub(FakeShell(), "off", [], available=False)
    b = _FakeProvider(name="b", entries=[_fe(provider="b", size=500)])

    discovery.scan([a, off, b], ScanFilters(), datetime.now(UTC), on_progress=on_progress)

    # ScanStarted first, naming only the available providers, in provider order.
    assert events[0] == discovery.ScanStarted(providers=("a", "b"))
    started = sorted(e.name for e in events if isinstance(e, discovery.ProviderStarted))
    assert started == ["a", "b"]
    finished = {
        e.timing.name: e.timing for e in events if isinstance(e, discovery.ProviderFinished)
    }
    assert set(finished) == {"a", "b"}
    assert (finished["a"].entries, finished["a"].bytes) == (2, 300)
    assert (finished["b"].entries, finished["b"].bytes) == (1, 500)
    # Each provider starts before it finishes, whatever the thread interleaving.
    for name in ("a", "b"):
        i_started = _index_of(
            events, lambda e: isinstance(e, discovery.ProviderStarted) and e.name == name
        )
        i_finished = _index_of(
            events, lambda e: isinstance(e, discovery.ProviderFinished) and e.timing.name == name
        )
        assert i_started < i_finished


def test_scan_reports_a_failed_provider_as_finished_with_zero_figures() -> None:
    events, on_progress = _collect_progress()
    boom = _Raising(FakeShell(), "boom", RuntimeError("disk gremlins"))

    discovery.scan([boom], ScanFilters(), datetime.now(UTC), on_progress=on_progress)

    finished = [e for e in events if isinstance(e, discovery.ProviderFinished)]
    assert [(e.timing.name, e.timing.entries, e.timing.bytes) for e in finished] == [("boom", 0, 0)]


def test_scan_with_no_available_providers_reports_only_scan_started() -> None:
    events, on_progress = _collect_progress()
    off = _Stub(FakeShell(), "off", [], available=False)

    discovery.scan([off], ScanFilters(), datetime.now(UTC), on_progress=on_progress)

    assert events == [discovery.ScanStarted(providers=())]


def test_scan_survives_a_raising_progress_callback(caplog) -> None:
    """A broken consumer is logged once per event and never changes the scan."""
    a = _FakeProvider(name="a", entries=[_fe(provider="a", size=100)])
    reference = discovery.scan([a], ScanFilters(), datetime.now(UTC))

    def bad(event: discovery.ScanProgressEvent) -> None:
        raise ValueError("consumer bug")

    with caplog.at_level("WARNING", logger="devdoctor.discovery"):
        report = discovery.scan([a], ScanFilters(), datetime.now(UTC), on_progress=bad)

    assert [e.id for e in report.entries] == [e.id for e in reference.entries]
    assert report.total_bytes() == reference.total_bytes()
    assert [pt.name for pt in report.per_provider] == ["a"]
    # ScanStarted + ProviderStarted + ProviderFinished, each logged once.
    failures = [r for r in caplog.records if "progress callback" in r.getMessage()]
    assert len(failures) == 3
    assert {"ScanStarted", "ProviderStarted", "ProviderFinished"} == {
        r.getMessage().split()[-1] for r in failures
    }
```

Put the `import threading` line with the other imports at the top of the file, not mid-file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_discovery.py -k "progress or scan_started" -v`
Expected: 4 failures — `AttributeError: module 'devdoctor.discovery' has no attribute 'ScanProgressEvent'` (or `TypeError: scan() got an unexpected keyword argument 'on_progress'`).

- [ ] **Step 3: Implement the events and the callback**

In `src/devdoctor/discovery.py`:

Add to the imports: `from collections.abc import Callable` and `from functools import partial`.

Below `_MAX_WORKERS = 8` add:

```python
@dataclass(frozen=True)
class ScanStarted:
    """Emitted once, before any provider runs; names the available providers in order."""

    providers: tuple[str, ...]


@dataclass(frozen=True)
class ProviderStarted:
    """Emitted from the worker thread when a provider's discover() begins."""

    name: str


@dataclass(frozen=True)
class ProviderFinished:
    """Emitted from the worker thread when a provider returns or fails.

    ``timing`` is what ``_discover_one`` computed: bytes and entries before
    reconciliation and containment. Right for "found so far"; the report's
    totals still come only from ``scan()``'s return value.
    """

    timing: ProviderTiming


ScanProgressEvent = ScanStarted | ProviderStarted | ProviderFinished
ScanProgressCallback = Callable[[ScanProgressEvent], None]


def _notify(on_progress: ScanProgressCallback | None, event: ScanProgressEvent) -> None:
    """Deliver one event; a consumer that raises is logged and can never alter a scan."""
    if on_progress is None:
        return
    try:
        on_progress(event)
    except Exception:
        logger.warning(
            "scan progress callback failed on %s", type(event).__name__, exc_info=True
        )
```

Change `_discover_one` to take the callback and report at both ends:

```python
def _discover_one(
    p: Provider, on_progress: ScanProgressCallback | None = None
) -> _ProviderResult:
```

At the top of its body, before `t0 = time.monotonic()`, add `_notify(on_progress, ProviderStarted(p.name))`. Replace the two `return _ProviderResult(...)` statements so each result is bound first and reported:

```python
        result = _ProviderResult(
            entries=[],
            diagnostics=diagnostics,
            timing=ProviderTiming(name=p.name, bytes=0, entries=0, duration_ms=dt_ms),
        )
        _notify(on_progress, ProviderFinished(result.timing))
        return result
```

and likewise for the success path (`result = _ProviderResult(entries=provider_entries, ...)`, then `_notify(...)`, then `return result`).

In `scan()`: add `on_progress: ScanProgressCallback | None = None` after `contain: bool = True` in the signature, and extend the docstring with one paragraph: "``on_progress`` receives ``ScanStarted`` once, then ``ProviderStarted``/``ProviderFinished`` per available provider from the worker threads; a raising callback is logged and ignored (spec §3)." After `available = [...]` add:

```python
    _notify(on_progress, ScanStarted(providers=tuple(p.name for p in available)))
```

and change the map call to `executor.map(partial(_discover_one, on_progress=on_progress), available)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_discovery.py -v`
Expected: all pass (the pre-existing tests are unaffected: no callback, no change).

- [ ] **Step 5: Lint and types**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format src tests && uv run --extra dev --extra web mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/devdoctor/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): report scan progress through an optional callback

ScanStarted, ProviderStarted and ProviderFinished events let a consumer follow
a scan provider by provider; a raising consumer is logged and never alters the
scan (#117).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: ScanProgressHub

**Files:**
- Create: `src/devdoctor/web/scan_progress.py`
- Test: `tests/web/test_scan_progress.py` (create)

**Interfaces:**
- Consumes: Task 1's `ScanStarted`, `ProviderStarted`, `ProviderFinished`, `ScanProgressCallback`; `ProviderTiming` from `devdoctor.types`.
- Produces (used by Task 3):
  ```python
  @dataclass(frozen=True) class ProviderProgress: name: str; status: Literal["pending","running","done"]; duration_ms: int | None; entries: int; bytes: int
  @dataclass(frozen=True) class ScanProgressSnapshot: scan_id: int; status: Literal["idle","running","done"]; started_at: datetime | None; total: int; done: int; running: tuple[str, ...]; entries: int; bytes: int; providers: tuple[ProviderProgress, ...]
      def to_json(self) -> dict[str, Any]
  class ScanProgressHub:
      def observer(self) -> ScanProgressCallback
      def snapshot(self) -> ScanProgressSnapshot
      def current(self) -> tuple[int, ScanProgressSnapshot]   # (version, snapshot), read atomically
      version: int (property)
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_scan_progress.py`:

```python
from __future__ import annotations

import threading

from devdoctor.discovery import ProviderFinished, ProviderStarted, ScanStarted
from devdoctor.types import ProviderTiming
from devdoctor.web.scan_progress import ScanProgressHub


def _timing(name: str, entries: int, size: int, duration_ms: int = 7) -> ProviderTiming:
    return ProviderTiming(name=name, bytes=size, entries=entries, duration_ms=duration_ms)


def test_idle_hub_snapshot() -> None:
    hub = ScanProgressHub()
    snap = hub.snapshot()
    assert (snap.scan_id, snap.status, snap.total, snap.done) == (0, "idle", 0, 0)
    assert snap.started_at is None
    assert snap.providers == ()
    assert hub.version == 0


def test_snapshot_follows_a_scan_through_to_done() -> None:
    hub = ScanProgressHub()
    report = hub.observer()

    report(ScanStarted(providers=("a", "b")))
    snap = hub.snapshot()
    assert (snap.scan_id, snap.status, snap.total, snap.done) == (1, "running", 2, 0)
    assert snap.started_at is not None
    assert [p.status for p in snap.providers] == ["pending", "pending"]
    assert hub.version == 1

    report(ProviderStarted("b"))
    snap = hub.snapshot()
    assert snap.running == ("b",)
    assert {p.name: p.status for p in snap.providers} == {"a": "pending", "b": "running"}

    report(ProviderFinished(_timing("b", entries=3, size=300)))
    snap = hub.snapshot()
    assert (snap.done, snap.entries, snap.bytes, snap.running) == (1, 3, 300, ())
    b = {p.name: p for p in snap.providers}["b"]
    assert (b.status, b.duration_ms, b.entries, b.bytes) == ("done", 7, 3, 300)
    assert snap.status == "running"

    report(ProviderStarted("a"))
    report(ProviderFinished(_timing("a", entries=1, size=50)))
    snap = hub.snapshot()
    assert (snap.status, snap.done, snap.entries, snap.bytes) == ("done", 2, 4, 350)
    assert hub.version == 5


def test_events_from_an_older_scan_are_ignored() -> None:
    hub = ScanProgressHub()
    first = hub.observer()
    second = hub.observer()
    first(ScanStarted(providers=("a",)))
    second(ScanStarted(providers=("x", "y")))
    version = hub.version

    first(ProviderStarted("a"))
    first(ProviderFinished(_timing("a", entries=9, size=900)))

    snap = hub.snapshot()
    assert snap.scan_id == 2
    assert (snap.total, snap.done, snap.entries) == (2, 0, 0)
    assert hub.version == version


def test_an_empty_scan_is_done_at_once() -> None:
    hub = ScanProgressHub()
    hub.observer()(ScanStarted(providers=()))
    snap = hub.snapshot()
    assert (snap.status, snap.total, snap.done) == ("done", 0, 0)


def test_unknown_provider_events_are_ignored() -> None:
    hub = ScanProgressHub()
    report = hub.observer()
    report(ScanStarted(providers=("a",)))
    report(ProviderStarted("ghost"))
    report(ProviderFinished(_timing("ghost", entries=1, size=1)))
    snap = hub.snapshot()
    assert (snap.done, snap.entries, snap.running) == (0, 0, ())


def test_concurrent_events_keep_totals_consistent() -> None:
    hub = ScanProgressHub()
    report = hub.observer()
    names = tuple(f"p{i}" for i in range(16))
    report(ScanStarted(providers=names))

    def run(name: str, size: int) -> None:
        report(ProviderStarted(name))
        report(ProviderFinished(_timing(name, entries=1, size=size)))

    threads = [threading.Thread(target=run, args=(n, i * 10)) for i, n in enumerate(names)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = hub.snapshot()
    assert (snap.status, snap.done, snap.entries) == ("done", 16, 16)
    assert snap.bytes == sum(i * 10 for i in range(16))
    assert hub.version == 1 + 2 * 16


def test_current_reads_version_and_snapshot_together() -> None:
    hub = ScanProgressHub()
    hub.observer()(ScanStarted(providers=("a",)))
    version, snap = hub.current()
    assert version == 1 and snap.status == "running"


def test_to_json_uses_the_documented_field_names() -> None:
    hub = ScanProgressHub()
    report = hub.observer()
    report(ScanStarted(providers=("a",)))
    report(ProviderStarted("a"))
    payload = hub.snapshot().to_json()
    assert set(payload) == {
        "scan_id", "status", "started_at", "total", "done", "running", "entries", "bytes",
        "providers",
    }
    assert payload["running"] == ["a"]
    assert payload["started_at"].endswith("+00:00")
    assert payload["providers"] == [
        {"name": "a", "status": "running", "duration_ms": None, "entries": 0, "bytes": 0}
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/web/test_scan_progress.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'devdoctor.web.scan_progress'`.

- [ ] **Step 3: Implement the hub**

Create `src/devdoctor/web/scan_progress.py`:

```python
"""Progress of the scan running in this server process, as a versioned snapshot.

``discovery.scan`` reports events from its worker threads through the callback
``observer()`` hands out; ``/api/scan/progress`` streams ``snapshot()`` whenever
``version`` changes. The hub never influences the scan (spec §2.4).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from devdoctor.discovery import (
    ProviderFinished,
    ProviderStarted,
    ScanProgressCallback,
    ScanProgressEvent,
    ScanStarted,
)

ProviderStatus = Literal["pending", "running", "done"]
ScanStatus = Literal["idle", "running", "done"]


@dataclass(frozen=True)
class ProviderProgress:
    name: str
    status: ProviderStatus
    duration_ms: int | None
    entries: int
    bytes: int


@dataclass(frozen=True)
class ScanProgressSnapshot:
    scan_id: int
    status: ScanStatus
    started_at: datetime | None
    total: int
    done: int
    running: tuple[str, ...]
    entries: int
    bytes: int
    providers: tuple[ProviderProgress, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "total": self.total,
            "done": self.done,
            "running": list(self.running),
            "entries": self.entries,
            "bytes": self.bytes,
            "providers": [
                {
                    "name": p.name,
                    "status": p.status,
                    "duration_ms": p.duration_ms,
                    "entries": p.entries,
                    "bytes": p.bytes,
                }
                for p in self.providers
            ],
        }


IDLE = ScanProgressSnapshot(
    scan_id=0,
    status="idle",
    started_at=None,
    total=0,
    done=0,
    running=(),
    entries=0,
    bytes=0,
    providers=(),
)


class ScanProgressHub:
    """Thread-safe: events arrive from the scan's worker threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = IDLE
        self._version = 0
        self._next_scan_id = 1

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> ScanProgressSnapshot:
        with self._lock:
            return self._snapshot

    def current(self) -> tuple[int, ScanProgressSnapshot]:
        """Version and snapshot read under one lock, so they always match."""
        with self._lock:
            return self._version, self._snapshot

    def observer(self) -> ScanProgressCallback:
        """A callback bound to the next scan id; older scans' events are then ignored."""
        with self._lock:
            scan_id = self._next_scan_id
            self._next_scan_id += 1

        def on_progress(event: ScanProgressEvent) -> None:
            self._apply(scan_id, event)

        return on_progress

    def _apply(self, scan_id: int, event: ScanProgressEvent) -> None:
        with self._lock:
            if scan_id < self._snapshot.scan_id:
                return
            if isinstance(event, ScanStarted):
                providers = tuple(
                    ProviderProgress(name, "pending", None, 0, 0) for name in event.providers
                )
                self._snapshot = _rebuild(scan_id, datetime.now(UTC), providers)
            elif scan_id != self._snapshot.scan_id:
                # A provider event before its ScanStarted, or from an unknown scan.
                return
            elif isinstance(event, ProviderStarted):
                self._snapshot = _update(self._snapshot, event.name, status="running")
            else:
                timing = event.timing
                self._snapshot = _update(
                    self._snapshot,
                    timing.name,
                    status="done",
                    duration_ms=timing.duration_ms,
                    entries=timing.entries,
                    bytes=timing.bytes,
                )
            self._version += 1


def _update(snapshot: ScanProgressSnapshot, name: str, **changes: Any) -> ScanProgressSnapshot:
    providers = tuple(
        replace(p, **changes) if p.name == name else p for p in snapshot.providers
    )
    return _rebuild(snapshot.scan_id, snapshot.started_at, providers)


def _rebuild(
    scan_id: int, started_at: datetime | None, providers: tuple[ProviderProgress, ...]
) -> ScanProgressSnapshot:
    done = [p for p in providers if p.status == "done"]
    return ScanProgressSnapshot(
        scan_id=scan_id,
        status="done" if len(done) == len(providers) else "running",
        started_at=started_at,
        total=len(providers),
        done=len(done),
        running=tuple(p.name for p in providers if p.status == "running"),
        entries=sum(p.entries for p in done),
        bytes=sum(p.bytes for p in done),
        providers=providers,
    )
```

Note `test_unknown_provider_events_are_ignored`: `_update` on a name that is not in `providers` changes nothing, but `_apply` still increments the version — that is acceptable (the test checks figures, not version). `test_concurrent_events_keep_totals_consistent` asserts `version == 1 + 2 * 16`, which holds because every event there names a known provider.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/web/test_scan_progress.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint and types**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format src tests && uv run --extra dev --extra web mypy`
Expected: clean. If mypy complains about `replace(p, **changes)`, type `changes` as `Any` (already) — `dataclasses.replace` accepts `**kwargs: Any`.

- [ ] **Step 6: Commit**

```bash
git add src/devdoctor/web/scan_progress.py tests/web/test_scan_progress.py
git commit -m "feat(web): hold the running scan's progress in a versioned hub

ScanProgressHub turns discovery progress events into one thread-safe snapshot
per scan; events from an older scan are ignored (#117).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `/api/scan/progress` and wiring into `/api/scan`

**Files:**
- Modify: `src/devdoctor/web/app.py` (state block ~line 94–99)
- Modify: `src/devdoctor/web/routes_scan.py` (imports; `scan()` ~line 60; new route)
- Modify: `docs/superpowers/specs/2026-09-15-scan-progress-stream-design.md` §5 (one clarification, see Step 3)
- Test: `tests/web/test_routes_scan.py` (append)

**Interfaces:**
- Consumes: `ScanProgressHub` (Task 2), `discovery.scan(..., on_progress=...)` (Task 1).
- Produces: `GET /api/scan/progress` → `text/event-stream` of `event: progress` frames whose `data` is `ScanProgressSnapshot.to_json()`; `app.state.scan_progress: ScanProgressHub`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_routes_scan.py`:

```python
import asyncio
import json

from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from devdoctor.discovery import ProviderFinished, ProviderStarted, ScanStarted
from devdoctor.types import ProviderTiming


def _app(tmp_path: Path, monkeypatch):
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    return build_app(shell, allowed_hosts={"testserver"}, static_dir=tmp_path)


async def _progress_events(es, limit: int, timeout: float = 5.0) -> list[dict]:
    """Read up to `limit` progress frames, skipping pings."""
    seen: list[dict] = []

    async def read() -> None:
        async for sse in es.aiter_sse():
            if sse.event != "progress":
                continue
            seen.append(json.loads(sse.data))
            if len(seen) >= limit:
                return

    await asyncio.wait_for(read(), timeout)
    return seen


async def test_scan_progress_stream_sends_the_current_snapshot_first(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        async with aconnect_sse(c, "GET", "/api/scan/progress", timeout=10) as es:
            assert es.response.headers["content-type"].startswith("text/event-stream")
            (first,) = await _progress_events(es, 1)
    assert first["status"] == "idle"
    assert first["scan_id"] == 0


async def test_scan_progress_stream_follows_the_hub_and_ends_on_done(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    report = app.state.scan_progress.observer()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        async with aconnect_sse(c, "GET", "/api/scan/progress", timeout=10) as es:
            (first,) = await _progress_events(es, 1)
            assert first["status"] == "idle"

            report(ScanStarted(providers=("a",)))
            (running,) = await _progress_events(es, 1)
            assert (running["status"], running["total"], running["done"]) == ("running", 1, 0)

            report(ProviderStarted("a"))
            report(ProviderFinished(ProviderTiming(name="a", bytes=42, entries=1, duration_ms=3)))
            frames = await _progress_events(es, 2)
            assert frames[-1]["status"] == "done"
            assert frames[-1]["bytes"] == 42

            # The generator ends after the transition it observed: the stream is exhausted.
            rest = []
            async for frame in es.aiter_sse():
                rest.append(frame)
            assert rest == []


async def test_scan_progress_stream_stays_open_after_an_initial_done(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    hub = app.state.scan_progress
    earlier = hub.observer()
    earlier(ScanStarted(providers=("a",)))
    earlier(ProviderStarted("a"))
    earlier(ProviderFinished(ProviderTiming(name="a", bytes=1, entries=1, duration_ms=1)))
    assert hub.snapshot().status == "done"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        async with aconnect_sse(c, "GET", "/api/scan/progress", timeout=10) as es:
            (first,) = await _progress_events(es, 1)
            assert first["status"] == "done"

            # A new scan starting afterwards still reaches this stream.
            hub.observer()(ScanStarted(providers=("b", "c")))
            (running,) = await _progress_events(es, 1)
            assert (running["status"], running["scan_id"], running["total"]) == ("running", 2, 2)


def test_scan_route_reports_progress_to_the_hub(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    hub = client.app.state.scan_progress
    assert hub.snapshot().status == "idle"

    resp = client.get("/api/scan", headers={"Host": "testserver"})

    assert resp.status_code == 200
    snap = hub.snapshot()
    assert snap.scan_id == 1
    assert snap.status == "done"
    assert snap.done == snap.total == len(resp.json()["per_provider"])
```

The final `async for` loop returns when the server closes the stream; `aconnect_sse`'s 10 s timeout bounds it. Put the new imports with the existing ones at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/web/test_routes_scan.py -k progress -v`
Expected: the three stream tests fail with a 404 (`httpx_sse.SSEError` or status assertion), and `test_scan_route_reports_progress_to_the_hub` fails with `AttributeError: 'State' object has no attribute 'scan_progress'`.

- [ ] **Step 3: Implement the route and the wiring**

`src/devdoctor/web/app.py`: import `from devdoctor.web.scan_progress import ScanProgressHub` and, right after `app.state.runner_registry = RunnerRegistry()`, add:

```python
    # Progress of the scan running in this process, for /api/scan/progress.
    app.state.scan_progress = ScanProgressHub()
```

`src/devdoctor/web/routes_scan.py`: add imports `import asyncio`, `from collections.abc import AsyncIterator`, `from sse_starlette.sse import EventSourceResponse`, and `from devdoctor.web.scan_progress import ScanProgressHub`. Add a module constant `_PROGRESS_POLL_S = 0.2`.

In `scan()`, change the discovery call to:

```python
    report = discovery.scan(
        providers_list,
        filters,
        datetime.now(UTC),
        on_progress=request.app.state.scan_progress.observer(),
    )
```

(only this route — leave the `recipe` route's `discovery.scan` call untouched). Add the new route after `scan()`:

```python
@router.get("/scan/progress")
async def scan_progress(request: Request) -> EventSourceResponse:
    """Stream the running scan's progress as `progress` events (spec §5).

    Sends the current snapshot at once, then a new one whenever the hub's
    version changes. Ends only after a transition into `done` it observed
    itself: an initial `done` or `idle` snapshot keeps the stream open because
    the client's own scan may not have reached the server yet.
    """
    hub: ScanProgressHub = request.app.state.scan_progress

    async def _stream() -> AsyncIterator[dict[str, str]]:
        version, snapshot = hub.current()
        yield {"event": "progress", "data": json.dumps(snapshot.to_json())}
        while True:
            await asyncio.sleep(_PROGRESS_POLL_S)
            new_version, new_snapshot = hub.current()
            if new_version == version:
                continue
            version, previous, snapshot = new_version, snapshot, new_snapshot
            yield {"event": "progress", "data": json.dumps(snapshot.to_json())}
            if previous.status != "done" and snapshot.status == "done":
                return

    return EventSourceResponse(_stream(), ping=10)
```

The route must be registered before FastAPI could match `/scan/{anything}` — there is no such route, so order does not matter, but keep it next to `scan()` for readability.

Spec clarification (§5 of the design doc): change "Ends after a `running → done` transition it observed itself" to "Ends after a transition into `done` it observed itself (from `running`, or straight from `idle` for a scan with no available providers)". The rest of §5 stands.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/web/test_routes_scan.py -v`
Expected: all pass, including the pre-existing scan tests.

- [ ] **Step 5: Full Python mirror**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy && uv run --extra dev --extra web pytest -q`
Expected: clean, all passed.

- [ ] **Step 6: Commit**

```bash
git add src/devdoctor/web/app.py src/devdoctor/web/routes_scan.py tests/web/test_routes_scan.py docs/superpowers/specs/2026-09-15-scan-progress-stream-design.md
git commit -m "feat(web): stream the running scan's progress at /api/scan/progress

/api/scan reports through the hub; the SSE route sends the snapshot whenever
it changes and ends after the transition into done it observed (#117).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Snapshot types and `formatScanProgress`

**Files:**
- Create: `web/src/lib/scanProgress.ts`
- Test: `web/tests/unit/scanProgress.test.ts` (create)

**Interfaces:**
- Consumes: `humanBytes` from `@/lib/format`.
- Produces (used by Tasks 5–7):
  ```ts
  export interface ProviderProgress { name: string; status: "pending" | "running" | "done"; duration_ms: number | null; entries: number; bytes: number }
  export interface ScanProgressSnapshot { scan_id: number; status: "idle" | "running" | "done"; started_at: string | null; total: number; done: number; running: string[]; entries: number; bytes: number; providers: ProviderProgress[] }
  export interface ScanProgressParts { providers: string; found: string | null; running: string | null; finishing: boolean }
  export function formatScanProgress(snapshot: ScanProgressSnapshot): ScanProgressParts
  export const MAX_RUNNING_NAMES = 3
  ```

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/scanProgress.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { formatScanProgress, type ScanProgressSnapshot } from "@/lib/scanProgress";

function snapshot(over: Partial<ScanProgressSnapshot> = {}): ScanProgressSnapshot {
  return {
    scan_id: 1,
    status: "running",
    started_at: "2026-09-15T10:00:00+00:00",
    total: 22,
    done: 12,
    running: ["xcode-development-data", "docker"],
    entries: 340,
    bytes: 45_200_000_000,
    providers: [],
    ...over,
  };
}

describe("formatScanProgress", () => {
  it("names the provider count, bytes found and the running providers", () => {
    const parts = formatScanProgress(snapshot());
    expect(parts.providers).toBe("12/22 providers");
    expect(parts.found).toBe("42.1G found");
    expect(parts.running).toBe("running: xcode-development-data, docker");
    expect(parts.finishing).toBe(false);
  });

  it("omits 'found' until a provider has finished, even at zero bytes", () => {
    expect(formatScanProgress(snapshot({ done: 0, bytes: 0 })).found).toBeNull();
    expect(formatScanProgress(snapshot({ done: 1, bytes: 0 })).found).toBe("0B found");
  });

  it("omits 'running' when nothing is running and caps the names at three", () => {
    expect(formatScanProgress(snapshot({ running: [] })).running).toBeNull();
    expect(formatScanProgress(snapshot({ running: ["a", "b", "c", "d", "e"] })).running).toBe(
      "running: a, b, c +2",
    );
  });

  it("flags finishing once every provider is done", () => {
    const parts = formatScanProgress(snapshot({ status: "done", done: 22, running: [] }));
    expect(parts.finishing).toBe(true);
    expect(parts.providers).toBe("22/22 providers");
  });
});
```

`humanBytes` (`web/src/lib/format.ts:16`) uses 1024-based units with one-letter suffixes, so 45,200,000,000 renders as `42.1G` and zero as `0B`; the expected strings above pin that real output.

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `web/`): `bunx vitest run tests/unit/scanProgress.test.ts`
Expected: `Failed to resolve import "@/lib/scanProgress"`.

- [ ] **Step 3: Implement**

Create `web/src/lib/scanProgress.ts`:

```ts
import { humanBytes } from "@/lib/format";

/** Mirror of ScanProgressSnapshot.to_json() in src/devdoctor/web/scan_progress.py. */
export interface ProviderProgress {
  name: string;
  status: "pending" | "running" | "done";
  duration_ms: number | null;
  entries: number;
  bytes: number;
}

export interface ScanProgressSnapshot {
  scan_id: number;
  status: "idle" | "running" | "done";
  started_at: string | null;
  total: number;
  done: number;
  running: string[];
  entries: number;
  bytes: number;
  providers: ProviderProgress[];
}

export interface ScanProgressParts {
  providers: string;
  /** null until a provider has finished, so a first provider that found nothing reads "0B found". */
  found: string | null;
  /** null when nothing is running; at most MAX_RUNNING_NAMES names, then " +N". */
  running: string | null;
  /** Every provider is done; the scan is reconciling, sorting and writing. */
  finishing: boolean;
}

export const MAX_RUNNING_NAMES = 3;

export function formatScanProgress(snapshot: ScanProgressSnapshot): ScanProgressParts {
  const shown = snapshot.running.slice(0, MAX_RUNNING_NAMES);
  const more = snapshot.running.length - shown.length;
  return {
    providers: `${snapshot.done}/${snapshot.total} providers`,
    found: snapshot.done > 0 ? `${humanBytes(snapshot.bytes)} found` : null,
    running:
      shown.length > 0 ? `running: ${shown.join(", ")}${more > 0 ? ` +${more}` : ""}` : null,
    finishing: snapshot.status === "done",
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bunx vitest run tests/unit/scanProgress.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/scanProgress.ts web/tests/unit/scanProgress.test.ts
git commit -m "feat(web): format a scan progress snapshot for the page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `useScanProgress` hook

**Files:**
- Create: `web/src/hooks/useScanProgress.ts`
- Test: `web/tests/unit/useScanProgress.test.ts` (create)

**Interfaces:**
- Consumes: `ScanProgressSnapshot` (Task 4); browser `EventSource`.
- Produces: `export function useScanProgress(active: boolean): ScanProgressSnapshot | null`; `export const SCAN_PROGRESS_URL = "/api/scan/progress"`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/useScanProgress.test.ts` (same fake-EventSource shape as `useSSE.test.ts`, extended with `closed` and `onerror`):

```ts
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useScanProgress } from "@/hooks/useScanProgress";
import type { ScanProgressSnapshot } from "@/lib/scanProgress";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  removeEventListener() {}
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    for (const fn of this.listeners[type] ?? []) {
      fn(new MessageEvent(type, { data: JSON.stringify(data) }));
    }
  }
}

function snap(over: Partial<ScanProgressSnapshot>): ScanProgressSnapshot {
  return {
    scan_id: 1,
    status: "running",
    started_at: null,
    total: 3,
    done: 1,
    running: ["b"],
    entries: 1,
    bytes: 10,
    providers: [],
    ...over,
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof FakeEventSource }).EventSource =
    FakeEventSource;
});

describe("useScanProgress", () => {
  it("opens the stream only while active and closes it when inactive", () => {
    const { result, rerender } = renderHook(({ active }) => useScanProgress(active), {
      initialProps: { active: false },
    });
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current).toBeNull();

    rerender({ active: true });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/scan/progress");

    rerender({ active: false });
    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(result.current).toBeNull();
  });

  it("keeps the latest snapshot and ignores idle ones", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ status: "idle", scan_id: 0, total: 0, done: 0})));
    expect(result.current).toBeNull();
    act(() => es.emit("progress", snap({ done: 1 })));
    act(() => es.emit("progress", snap({ done: 2 })));
    expect(result.current?.done).toBe(2);
  });

  it("ignores a snapshot from an older scan than one already shown", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ scan_id: 5, done: 1 })));
    act(() => es.emit("progress", snap({ scan_id: 4, status: "done", done: 3 })));
    expect(result.current?.scan_id).toBe(5);
    expect(result.current?.done).toBe(1);
  });

  it("closes on a done snapshot and keeps it until inactive", () => {
    const { result, rerender } = renderHook(({ active }) => useScanProgress(active), {
      initialProps: { active: true },
    });
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ status: "done", done: 3, running: [] })));
    expect(es.closed).toBe(true);
    expect(result.current?.status).toBe("done");
    rerender({ active: false });
    expect(result.current).toBeNull();
  });

  it("keeps the last value on a stream error", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ done: 2 })));
    act(() => es.onerror?.(new Event("error")));
    expect(result.current?.done).toBe(2);
  });

  it("closes the stream on unmount", () => {
    const { unmount } = renderHook(() => useScanProgress(true));
    unmount();
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bunx vitest run tests/unit/useScanProgress.test.ts`
Expected: `Failed to resolve import "@/hooks/useScanProgress"`.

- [ ] **Step 3: Implement the hook**

Create `web/src/hooks/useScanProgress.ts`:

```ts
import { useEffect, useState } from "react";
import type { ScanProgressSnapshot } from "@/lib/scanProgress";

export const SCAN_PROGRESS_URL = "/api/scan/progress";

/**
 * The running scan's latest progress snapshot while `active`, else null.
 *
 * Progress is decoration on top of the scan query: an error leaves the last
 * value in place and nothing reconnects; `idle` snapshots and any snapshot
 * from an older scan than one already shown are ignored, so a stale "done"
 * cannot flash before the new scan starts. The stream closes on `done`, on
 * `active` turning false, and on unmount.
 */
export function useScanProgress(active: boolean): ScanProgressSnapshot | null {
  const [snapshot, setSnapshot] = useState<ScanProgressSnapshot | null>(null);

  useEffect(() => {
    if (!active) {
      setSnapshot(null);
      return;
    }
    const es = new EventSource(SCAN_PROGRESS_URL);
    let highestScanId = 0;
    const onProgress = (event: MessageEvent) => {
      let next: ScanProgressSnapshot;
      try {
        next = JSON.parse(event.data) as ScanProgressSnapshot;
      } catch {
        return;
      }
      if (next.status === "idle" || next.scan_id < highestScanId) return;
      highestScanId = next.scan_id;
      setSnapshot(next);
      if (next.status === "done") es.close();
    };
    es.addEventListener("progress", onProgress);
    es.onerror = () => {
      /* keep the last snapshot; the scan query is unaffected */
    };
    return () => {
      es.removeEventListener("progress", onProgress);
      es.close();
    };
  }, [active]);

  return snapshot;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bunx vitest run tests/unit/useScanProgress.test.ts`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/useScanProgress.ts web/tests/unit/useScanProgress.test.ts
git commit -m "feat(web): subscribe to scan progress while the scan query fetches

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `ScanProgressLine` and page wiring

**Files:**
- Create: `web/src/components/ScanProgressLine.tsx`
- Modify: `web/src/pages/Scan.tsx` (imports; `useCountdown` call ~line 57; the `rescanning…` span ~line 152–161; the `scanning…` block ~line 174–178; remove `ScanCountdown` at the bottom)
- Modify: `web/src/pages/Dashboard.tsx` (imports; after `const disk = useScan({...})` ~line 45; `loadingLabel` ~line 131)
- Test: `web/tests/unit/ScanProgressLine.test.tsx` (create)

**Interfaces:**
- Consumes: `formatScanProgress`, `ScanProgressSnapshot` (Task 4); `useScanProgress` (Task 5); `formatMs` from `@/lib/format`.
- Produces: `export function ScanProgressLine({ progress, remainingMs, bar }: { progress: ScanProgressSnapshot | null; remainingMs: number | null; bar?: boolean })`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/ScanProgressLine.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScanProgressLine } from "@/components/ScanProgressLine";
import type { ScanProgressSnapshot } from "@/lib/scanProgress";

function snap(over: Partial<ScanProgressSnapshot> = {}): ScanProgressSnapshot {
  return {
    scan_id: 1,
    status: "running",
    started_at: null,
    total: 22,
    done: 12,
    running: ["xcode-development-data", "docker"],
    entries: 340,
    bytes: 45_200_000_000,
    providers: [],
    ...over,
  };
}

describe("ScanProgressLine", () => {
  it("shows only the countdown before the first snapshot", () => {
    const { container } = render(<ScanProgressLine progress={null} remainingMs={80_000} />);
    expect(container.textContent).toBe(" · ~1m 20s left, from past scans");
  });

  it("renders the progress parts, then the countdown", () => {
    const { container } = render(<ScanProgressLine progress={snap()} remainingMs={80_000} />);
    expect(container.textContent).toBe(
      " · 12/22 providers · 42.1G found · running: xcode-development-data, docker · ~1m 20s left, from past scans",
    );
  });

  it("says finishing once every provider is done", () => {
    render(<ScanProgressLine progress={snap({ status: "done", done: 22, running: [] })} remainingMs={0} />);
    expect(screen.getByText(/22\/22 providers · finishing…/)).toBeInTheDocument();
  });

  it("renders a labelled bar when asked", () => {
    render(<ScanProgressLine progress={snap()} remainingMs={null} bar />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "12");
    expect(bar).toHaveAttribute("aria-valuemax", "22");
  });

  it("renders no bar without a snapshot", () => {
    render(<ScanProgressLine progress={null} remainingMs={null} bar />);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});
```

`42.1G` is what `humanBytes` renders for 45,200,000,000 (1024-based, one-letter unit), as in Task 4.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bunx vitest run tests/unit/ScanProgressLine.test.tsx`
Expected: `Failed to resolve import "@/components/ScanProgressLine"`.

- [ ] **Step 3: Implement the component**

Create `web/src/components/ScanProgressLine.tsx`:

```tsx
import { formatMs } from "@/lib/format";
import { formatScanProgress, type ScanProgressSnapshot } from "@/lib/scanProgress";

/**
 * One line of scan progress for the Disk page: provider count, bytes found,
 * running providers, then the countdown from past scans. Without a snapshot
 * it shows only the countdown, exactly what the page showed before #117.
 */
export function ScanProgressLine({
  progress,
  remainingMs,
  bar = false,
}: {
  progress: ScanProgressSnapshot | null;
  remainingMs: number | null;
  bar?: boolean;
}) {
  const parts = progress ? formatScanProgress(progress) : null;
  const words: string[] = [];
  if (parts) {
    words.push(parts.providers);
    if (parts.finishing) words.push("finishing…");
    else {
      if (parts.found) words.push(parts.found);
      if (parts.running) words.push(parts.running);
    }
  }
  if (remainingMs !== null) {
    words.push(remainingMs <= 0 ? "longer than past scans" : `~${formatMs(remainingMs)} left, from past scans`);
  }
  return (
    <>
      {words.map((word) => ` · ${word}`).join("")}
      {bar && progress && (
        <div
          role="progressbar"
          aria-label="scan progress"
          aria-valuemin={0}
          aria-valuemax={progress.total}
          aria-valuenow={progress.done}
          className="mt-2 h-1 w-64 rounded bg-bg-elev-2 overflow-hidden"
        >
          <div
            className="h-full bg-risk-safe transition-[width]"
            style={{ width: progress.total > 0 ? `${(100 * progress.done) / progress.total}%` : "0%" }}
          />
        </div>
      )}
    </>
  );
}
```

In `web/src/pages/Scan.tsx`:

- Add imports: `import { ScanProgressLine } from "@/components/ScanProgressLine";` and `import { useScanProgress } from "@/hooks/useScanProgress";`.
- After `const remainingMs = useCountdown(eta?.etaMs ?? null, isFetching);` add `const progress = useScanProgress(isFetching);`.
- Replace `<ScanCountdown remainingMs={remainingMs} />` inside the `rescanning…` span with `<ScanProgressLine progress={progress} remainingMs={remainingMs} />`.
- Replace the loading block's `<ScanCountdown remainingMs={remainingMs} />` with `<ScanProgressLine progress={progress} remainingMs={remainingMs} bar />`.
- Delete the `ScanCountdown` function at the bottom of the file and its comment; `formatMs` stays imported only if something else in the file uses it — if not, remove it from the import line (eslint will say).

In `web/src/pages/Dashboard.tsx`:

- Add imports: `import { useScanProgress } from "@/hooks/useScanProgress";` and `import { formatScanProgress } from "@/lib/scanProgress";`.
- After the `const disk = useScan({...});` block add `const diskProgress = useScanProgress(disk.isFetching);`.
- Change the `loadingLabel` prop of the disk `ResourcePanel` to:

```tsx
            loadingLabel={
              (diskHasNoCache ? "running first full scan…" : "loading…") +
              (diskProgress ? ` · ${formatScanProgress(diskProgress).providers}` : "")
            }
```

- [ ] **Step 4: Run the tests, typecheck and lint**

Run: `bunx vitest run && bun run typecheck && bun run lint`
Expected: all tests pass (the new file: 5 passed); no new lint warnings (the pre-existing `react-hooks/exhaustive-deps` warnings in Dashboard/MosaicTreemap/useSSE are known).

- [ ] **Step 5: Build and run the existing e2e suite**

Run: `bun run test:e2e`
Expected: 8 passed (the loading text still starts with `scanning…`, and the countdown reads as before). Then, from the repo root: `git checkout -- src/devdoctor/web/_static/dist/index.html`.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/ScanProgressLine.tsx web/src/pages/Scan.tsx web/src/pages/Dashboard.tsx web/tests/unit/ScanProgressLine.test.tsx
git commit -m "feat(web): show provider-by-provider progress while a scan runs

The Disk page's scanning and rescanning states carry the provider count,
bytes found and running providers ahead of the countdown; the Dashboard's
loading label carries the count (#117).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Playwright specs and documentation

**Files:**
- Create: `web/tests/e2e/progress.spec.ts`
- Modify: `CHANGELOG.md` (`## [Unreleased]` → `### Added`, top of the list), `README.md` ("## Web UI" section, after the Flags list)

**Interfaces:**
- Consumes: the e2e fixture (`web/tests/e2e/fixture.ts`: `CACHE_LABEL`), `/api/scan/progress` (Task 3), the page wiring (Task 6).

- [ ] **Step 1: Write the failing specs**

Create `web/tests/e2e/progress.spec.ts`:

```ts
import { expect, test } from "@playwright/test";
import { CACHE_LABEL } from "./fixture";

const SCAN_URL = /\/api\/(disk\/)?scan(\?|$)/;
const PROGRESS_URL = /\/api\/scan\/progress(\?|$)/;

function frame(data: object): string {
  return `event: progress\ndata: ${JSON.stringify(data)}\n\n`;
}

const RUNNING = {
  scan_id: 1,
  status: "running",
  started_at: "2026-09-15T10:00:00+00:00",
  total: 3,
  done: 1,
  running: [CACHE_LABEL],
  entries: 1,
  bytes: 300_000,
  providers: [],
};

test("the loading line follows the progress stream while the scan is held (#117)", async ({
  page,
}) => {
  // The fixture scan finishes in milliseconds, so hold the scan and answer the
  // stream with a canned snapshot: this proves the page wires the stream in.
  await page.route(SCAN_URL, (route) => {
    setTimeout(() => void route.continue().catch(() => undefined), 4000);
  });
  await page.route(PROGRESS_URL, (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: frame(RUNNING) }),
  );
  await page.goto("/disk");

  const loading = page.getByText(/^scanning…/);
  await expect(loading).toContainText("1/3 providers");
  await expect(loading).toContainText(`running: ${CACHE_LABEL}`);
  await expect(page.getByRole("progressbar", { name: "scan progress" })).toHaveAttribute(
    "aria-valuenow",
    "1",
  );

  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  await expect(loading).toHaveCount(0);
});

test("the loading line says finishing once every provider is done (#117)", async ({ page }) => {
  await page.route(SCAN_URL, (route) => {
    setTimeout(() => void route.continue().catch(() => undefined), 4000);
  });
  await page.route(PROGRESS_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: frame({ ...RUNNING, status: "done", done: 3, running: [] }),
    }),
  );
  await page.goto("/disk");

  await expect(page.getByText(/^scanning…/)).toContainText("3/3 providers · finishing…");
});

test("the server answers /api/scan/progress with an event stream (#117)", async ({ page }) => {
  await page.goto("/disk");
  const first = await page.evaluate(async () => {
    const controller = new AbortController();
    const response = await fetch("/api/scan/progress", { signal: controller.signal });
    const reader = response.body!.getReader();
    const { value } = await reader.read();
    controller.abort();
    return {
      contentType: response.headers.get("content-type"),
      text: new TextDecoder().decode(value),
    };
  });
  expect(first.contentType).toContain("text/event-stream");
  expect(first.text).toContain("event: progress");
  expect(first.text).toContain('"scan_id"');
});
```

Note on the canned stream: `route.fulfill` sends the whole body at once, so each spec uses one snapshot; when the body ends the browser's `EventSource` reconnects after a few seconds and receives the same body again, which changes nothing.

- [ ] **Step 2: Run the specs to verify they fail**

Run: `bun run test:e2e -- tests/e2e/progress.spec.ts` (or `bun run build && bunx playwright test tests/e2e/progress.spec.ts`)
Expected: with Tasks 1–6 done these pass. To watch them fail for the right reason, run them once against `main`'s page: `git show origin/main:web/src/pages/Scan.tsx > web/src/pages/Scan.tsx`, rebuild, run — the first two fail (`1/3 providers` never appears) — then `git checkout -- web/src/pages/Scan.tsx` and rebuild. The third spec fails against a server without Task 3 (404); it needs no swap if Task 3 is already merged — say so in the task report.

- [ ] **Step 3: Documentation**

`CHANGELOG.md`, under `## [Unreleased]` → `### Added`, insert at the top of the list:

```markdown
- **Live scan progress in the web UI.** While a scan runs, the Disk page shows
  how many providers have finished, the bytes found so far and which providers
  are running, ahead of the countdown from past scans; the Dashboard's loading
  label shows the provider count. The page reads a new server-sent-events
  endpoint, `GET /api/scan/progress`, that mirrors the scan running in the
  server; `GET /api/scan` is unchanged. (#117)
```

`README.md`, after the Flags list in "## Web UI", add:

```markdown
While a scan runs, the Disk page shows live progress — providers finished,
bytes found so far and which providers are running — over
`GET /api/scan/progress` (server-sent events).
```

- [ ] **Step 4: Full web mirror**

Run (in `web/`): `bun run lint && bun run typecheck && bun run test && bun run test:e2e`
Expected: all green, e2e 11 passed. Then from the repo root: `git checkout -- src/devdoctor/web/_static/dist/index.html`.

- [ ] **Step 5: Commit**

```bash
git add web/tests/e2e/progress.spec.ts CHANGELOG.md README.md
git commit -m "test(web): cover the scan progress line and endpoint end to end

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** §3 (events, isolation, timing semantics) → Task 1. §4 (hub, scan_id, snapshot fields, version, empty scan) → Task 2. §5 (endpoint, initial snapshot, 200 ms poll, end rule, wiring only `/api/scan`) → Task 3 (with the one clarification about an empty scan's `idle → done`). §6.1 hook → Task 5. §6.2 formatting → Task 4. §6.3 rendering, bar with aria, Dashboard label → Task 6. §7 failure modes: callback raising (Task 1 test), overlap (Task 2 test), stream before/after scan (Task 3 tests), EventSource error (Task 5 test). §8 tests: all listed cases have a task; §10 docs → Task 7.

**Placeholders.** None; every step carries its code. The `humanBytes` strings pinned in Tasks 4 and 6 (`42.1G`, `0B`) were read from `format.ts`.

**Type consistency.** `ScanProgressCallback`/events are defined in Task 1 and imported by name in Tasks 2–3; the JSON field names in Task 2's `to_json` match Task 4's `ScanProgressSnapshot` interface and the e2e frames in Task 7; `useScanProgress(active)` returns `ScanProgressSnapshot | null` as consumed in Task 6; `ScanProgressLine` props match their use in Task 6 and the e2e `progressbar` name in Task 7.
