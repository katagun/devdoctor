# `devdoctor clean` Feedback and Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `devdoctor clean --execute` show what it is about to do (itemized plan, human sizes) before the confirmation, report every entry as it runs, summarise with the real free-space delta, record every run in the audit log, and let `devdoctor history` read runs back.

**Architecture:** The cleanup state machine (`cleanup.iter_cleanup_events`) is unchanged in what it decides; it gains a `plan` on `ConfirmRequired` and the sync/async adapters gain an `on_event` observer. All CLI output moves into one `CleanupPresenter` in `rendering.py` that observes those events. A shared `cleanup_audit.build_event` produces the audit record for both the web runner and the CLI, written through the same storage backend; a new `history` command reads it.

**Tech Stack:** Python 3.12, click, Rich, pytest (asyncio auto mode), `FakeShell` from `tests/conftest.py`; ruff (line length 100), `mypy --strict`.

**Spec:** `docs/superpowers/specs/2026-09-16-clean-cli-feedback-design.md`

## Global Constraints

- Every `--execute` run prints the itemized plan before the final confirmation, whatever flags are set; `--yes` skips only that confirmation (spec §2.1, §6).
- The observer is fire-and-forget: exceptions are logged once at warning level with the event class name and swallowed; a presenter can never abort or alter a cleanup (spec §3.1).
- `ConfirmRequired.plan` lists the approved entries in execution order with the same action list `_run_actions` executes (spec §3.2).
- Human-readable sizes everywhere in `clean` and `history`; exact bytes only in `--json` and the audit record (spec §2.5). Totals are labelled "estimated" (spec §2.6).
- The audit event keeps every existing key (`type`, `job_id`, `outcome`, `total_freed_bytes`, `total_estimated_reclaimed_bytes`, `bytes_verified`, `results[{entry_id, status, freed_bytes, message, bytes_verified}]`, `error`) and adds `source`, `at`, `plan`, per-result `provider`/`label`/`path`, `free_before_bytes`, `free_after_bytes` (spec §5.1).
- The CLI writes through `build_storage(load_app_settings())`; a write failure is logged with traceback and never changes the exit code (spec §5.1).
- Without a TTY and without `--yes`, `clean --execute` aborts before executing with `no terminal to confirm on; pass --yes to run unattended` (spec §6).
- Exit code 2 when any entry failed, as today (spec §4.4).
- Output goes through Rich with control characters stripped (`_strip_controls`), home shown as `~` (spec §4).
- Every test is written before the code it covers and watched fail (spec §8).
- Python: `uv run --extra dev --extra web ...` from the repo root; ruff line length 100; `mypy --strict`; commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. The pre-commit hook may print "Unstaged files detected"/"Restored changes" — normal. Never use `git stash`. Use `git diff --no-ext-diff --no-color` for diffs.

---

## File structure

| File | Responsibility |
|---|---|
| `src/devdoctor/units.py` (create) | `human_bytes`, `human_bytes_or_unknown`, `estimated_bytes` — the one byte formatter, importable by core and presentation |
| `src/devdoctor/cleanup.py` (modify) | `PlannedEntry`, `ConfirmRequired.plan`, `CleanupObserver`, `_notify_observer`, `on_event` on `run`/`run_async`, `_execution_order`, human `_confirm_summary` |
| `src/devdoctor/cleanup_audit.py` (create) | `build_event`, `estimated_reclaimed_bytes`, `all_bytes_verified` |
| `src/devdoctor/web/cleanup_runner.py` (modify) | use `cleanup_audit.build_event`; capture the plan from `ConfirmRequired` |
| `src/devdoctor/rendering.py` (modify) | `CleanupPresenter` (scan progress, plan table, progress lines, summary, per-entry prompt); `real_prompts` removed |
| `src/devdoctor/cli.py` (modify) | `clean` wiring, `--yes`, `--risk`, help text, no-TTY abort, free-space delta, audit write; new `history` command |
| `tests/test_units.py`, `tests/test_cleanup.py`, `tests/test_cleanup_audit.py`, `tests/test_rendering.py`, `tests/test_cli.py`, `tests/web/test_cleanup_runner.py` | pytest |
| `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md` | docs |

---

### Task 1: One byte formatter (`units.py`)

**Files:**
- Create: `src/devdoctor/units.py`
- Modify: `src/devdoctor/rendering.py` (`_human_bytes`, `_human_bytes_or_unknown`, `_estimated_bytes` ~line 176–194 become thin aliases)
- Test: `tests/test_units.py` (create)

**Interfaces:**
- Produces (used by Tasks 2, 4, 5):
  ```python
  def human_bytes(n: int) -> str            # 0 -> "0B", 1536 -> "1.5K", 5_600_000_000 -> "5.2G", negative keeps the sign
  def human_bytes_or_unknown(n: int | None) -> str   # None -> "unknown"
  def estimated_bytes(n: int | None) -> str          # None -> "unknown", else "~" + human_bytes(n)
  ```

- [ ] **Step 1: Write the failing test**

Create `tests/test_units.py`:

```python
from devdoctor.units import estimated_bytes, human_bytes, human_bytes_or_unknown


def test_human_bytes_uses_1024_units_with_one_decimal() -> None:
    assert human_bytes(0) == "0B"
    assert human_bytes(512) == "512B"
    assert human_bytes(1536) == "1.5K"
    assert human_bytes(5_600_000_000) == "5.2G"
    assert human_bytes(-2048) == "-2.0K"


def test_unknown_and_estimate_variants() -> None:
    assert human_bytes_or_unknown(None) == "unknown"
    assert human_bytes_or_unknown(2048) == "2.0K"
    assert estimated_bytes(None) == "unknown"
    assert estimated_bytes(2048) == "~2.0K"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev --extra web pytest tests/test_units.py -q`
Expected: `ModuleNotFoundError: No module named 'devdoctor.units'`.

- [ ] **Step 3: Implement**

Create `src/devdoctor/units.py` with the body of `rendering._human_bytes` and its two variants:

```python
"""Byte formatting shared by the core and every presentation layer."""

from __future__ import annotations

_BYTES_UNIT_STEP = 1024


def human_bytes(n: int) -> str:
    sign = "-" if n < 0 else ""
    value: float = float(abs(n))
    for unit in ("B", "K", "M", "G", "T", "P"):
        if value < _BYTES_UNIT_STEP or unit == "P":
            return f"{sign}{value:.0f}{unit}" if unit == "B" else f"{sign}{value:.1f}{unit}"
        value /= _BYTES_UNIT_STEP
    return f"{sign}{value:.1f}P"


def human_bytes_or_unknown(n: int | None) -> str:
    return "unknown" if n is None else human_bytes(n)


def estimated_bytes(n: int | None) -> str:
    return "unknown" if n is None else f"~{human_bytes(n)}"
```

In `src/devdoctor/rendering.py` delete the bodies of `_human_bytes`, `_human_bytes_or_unknown`, `_estimated_bytes` and the `_BYTES_UNIT_STEP` constant, replacing them with:

```python
from devdoctor.units import estimated_bytes, human_bytes, human_bytes_or_unknown

_human_bytes = human_bytes
_human_bytes_or_unknown = human_bytes_or_unknown
_estimated_bytes = estimated_bytes
```

(keep `_DAYS_PER_MONTH` / `_DAYS_PER_YEAR`, which `_staleness` uses).

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra web pytest tests/test_units.py tests/test_rendering.py -q` (if `tests/test_rendering.py` does not exist yet, run `tests/test_units.py tests/test_cli.py`).
Expected: all pass.

- [ ] **Step 5: Lint, types, commit**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format src tests && uv run --extra dev --extra web mypy`
Then:

```bash
git add src/devdoctor/units.py src/devdoctor/rendering.py tests/test_units.py
git commit -m "refactor: share the byte formatter between core and rendering

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Observer and plan in the cleanup core

**Files:**
- Modify: `src/devdoctor/cleanup.py` (event classes ~line 44–95; `iter_cleanup_events` ~line 103; `_iter_execute` ~line 236; `run`/`run_async` ~line 341–400; `_confirm_summary` ~line 413)
- Test: `tests/test_cleanup.py` (append)

**Interfaces:**
- Consumes: `units.human_bytes` (Task 1); existing `render_cleanup_action`, `cleanup_action_argv`, `Entry.cleanup_actions()`, `Entry.reclaimable_bytes`.
- Produces (used by Tasks 3–5):
  ```python
  @dataclass(frozen=True)
  class PlannedEntry:
      entry: Entry
      actions: tuple[CleanupAction, ...]
      estimate_bytes: int | None
      @property
      def lines(self) -> tuple[str, ...]      # render_cleanup_action per action
  class ConfirmRequired:  # existing fields + plan: tuple[PlannedEntry, ...] = ()
  CleanupObserver = Callable[[CleanupEvent], None]
  def run(report, *, shell, prompt_choice, confirm, opts, verify=None, on_event: CleanupObserver | None = None)
  async def run_async(report, *, run_line, prompt_choice, confirm, opts, verify=None, on_event: CleanupObserver | None = None)
  def _confirm_summary(event: ConfirmRequired) -> str   # "Execute these 16 entries (~15.7G estimated, +2 unknown)?"
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cleanup.py` (it already has `_report`, `_e`, `FakeShell`, `run`, `CleanupOpts`, `ShellResult`, `Risk`):

```python
import logging

from devdoctor import cleanup
from devdoctor.types import AdviceAction, CommandAction


def _events_of(report, opts, *, shell=None, prompt=None, confirm=None):
    seen: list[object] = []
    results = run(
        report,
        shell=shell or FakeShell(),
        prompt_choice=prompt or (lambda entry: "y"),
        confirm=confirm or (lambda msg: True),
        opts=opts,
        on_event=seen.append,
    )
    return seen, results


def test_run_delivers_every_event_to_the_observer_in_order() -> None:
    a = _e("a", "1", 100)
    shell = FakeShell(responses={("rm", "-rf", "--", "/1"): ShellResult(0, "", "")})
    seen, results = _events_of(_report(a), CleanupOpts(execute=True), shell=shell)

    kinds = [type(e).__name__ for e in seen]
    assert kinds == ["PromptRequired", "ConfirmRequired", "ExecuteStep", "EntryResolved"]
    assert [r.status for r in results] == ["ok"]


def test_confirm_required_carries_the_plan_in_execution_order() -> None:
    small = _e("a", "small", 10)
    big = _e("a", "big", 1000)
    unknown = Entry(
        provider="b",
        id="hint",
        path=Path("/hint"),
        label="b/hint",
        size_bytes=5,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
        actions=(AdviceAction("run the tool yourself"),),
        usage=None,
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "--", "/small"): ShellResult(0, "", ""),
            ("rm", "-rf", "--", "/big"): ShellResult(0, "", ""),
        }
    )
    seen, _ = _events_of(
        _report(small, big, unknown), CleanupOpts(execute=True, yes_safe=True), shell=shell
    )

    (confirm,) = [e for e in seen if isinstance(e, cleanup.ConfirmRequired)]
    assert [p.entry.id for p in confirm.plan] == [e.id for e in confirm.approved]
    by_id = {p.entry.id: p for p in confirm.plan}
    assert by_id["small"].lines == ("rm -rf -- /small",)
    assert by_id["small"].estimate_bytes == 10
    assert by_id["hint"].lines == ("echo 'run the tool yourself'",)
    assert by_id["hint"].estimate_bytes == 5
    # Execution order: the plan's order is the order EntryResolved arrives in.
    resolved = [e.result.entry_id for e in seen if isinstance(e, cleanup.EntryResolved)]
    assert resolved == [p.entry.id for p in confirm.plan]


def test_plan_is_empty_when_nothing_is_approved() -> None:
    seen, _ = _events_of(_report(_e("a", "1", 100)), CleanupOpts(execute=True), prompt=lambda e: "n")
    assert not any(isinstance(e, cleanup.ConfirmRequired) for e in seen)


def test_a_raising_observer_never_changes_the_run(caplog) -> None:
    a = _e("a", "1", 100)
    shell = FakeShell(responses={("rm", "-rf", "--", "/1"): ShellResult(0, "", "")})
    reference = run(
        _report(a), shell=shell, prompt_choice=lambda e: "y", confirm=lambda m: True,
        opts=CleanupOpts(execute=True),
    )

    def bad(event: object) -> None:
        raise ValueError("presenter bug")

    with caplog.at_level(logging.WARNING, logger="devdoctor.cleanup"):
        results = run(
            _report(a), shell=FakeShell(responses=shell.responses), prompt_choice=lambda e: "y",
            confirm=lambda m: True, opts=CleanupOpts(execute=True), on_event=bad,
        )

    assert [(r.entry_id, r.status) for r in results] == [(r.entry_id, r.status) for r in reference]
    messages = [r.getMessage() for r in caplog.records if "cleanup observer" in r.getMessage()]
    assert {m.split()[-1] for m in messages} == {
        "PromptRequired", "ConfirmRequired", "ExecuteStep", "EntryResolved"
    }


def test_confirm_summary_is_human_readable() -> None:
    a = _e("a", "1", 5_600_000_000)
    event = cleanup.ConfirmRequired(approved=[a], total_bytes=5_600_000_000, unknown_entries=0)
    assert cleanup._confirm_summary(event) == "Execute these 1 entries (~5.2G estimated)?"
    event = cleanup.ConfirmRequired(approved=[a, a], total_bytes=1024, unknown_entries=2)
    assert cleanup._confirm_summary(event) == "Execute these 2 entries (~1.0K estimated, +2 unknown)?"


async def test_run_async_delivers_events_to_the_observer() -> None:
    a = _e("a", "1", 100)

    async def run_line(argv):
        return ShellResult(0, "", "")

    async def prompt(entry):
        return "y"

    async def confirm(msg):
        return True

    seen: list[object] = []
    results = await cleanup.run_async(
        _report(a), run_line=run_line, prompt_choice=prompt, confirm=confirm,
        opts=CleanupOpts(execute=True), on_event=seen.append,
    )
    assert [type(e).__name__ for e in seen] == [
        "PromptRequired", "ConfirmRequired", "ExecuteStep", "EntryResolved"
    ]
    assert [r.status for r in results] == ["ok"]
```

Note the raising-observer test records warnings through a **monkeypatched logger**-free `caplog` — `tests/test_cli.py` leaves the `devdoctor` logger with `propagate=False` for the whole pytest process (see the #120 fix), so instead of `caplog` use the same technique as `tests/test_discovery.py::test_scan_survives_a_raising_progress_callback`: monkeypatch `cleanup.logger` with a small recorder whose `warning(msg, *args, **kwargs)` appends `msg % args`, and assert on those messages. Rewrite the test accordingly (signature `(monkeypatch)` instead of `(caplog)`); the assertions stay the same.

The `Entry(...)` constructor above uses keyword names from `src/devdoctor/types.py:162` (`provider, id, path, label, size_bytes, mtime, risk, recipe, actions, usage`); check the file for any required field this omits and add it.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_cleanup.py -k "observer or plan or confirm_summary or run_async_delivers" -q`
Expected: failures — `TypeError: run() got an unexpected keyword argument 'on_event'`, `AttributeError: ... has no attribute 'plan'`, and the summary assertion showing the old `... ~5600000000 bytes?` text.

- [ ] **Step 3: Implement**

In `src/devdoctor/cleanup.py`:

Add `import logging` and `logger = logging.getLogger(__name__)` near the top; import `human_bytes` from `devdoctor.units`.

Add after `ExecuteStep`:

```python
@dataclass(frozen=True)
class PlannedEntry:
    """One approved entry as it will run: the same actions ``_run_actions`` executes."""

    entry: Entry
    actions: tuple[CleanupAction, ...]
    estimate_bytes: int | None

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(render_cleanup_action(action) for action in self.actions)
```

Extend `ConfirmRequired`:

```python
@dataclass
class ConfirmRequired:
    approved: list[Entry]
    total_bytes: int
    unknown_entries: int = 0
    # The approved entries in execution order, with what will run (spec §3.2).
    plan: tuple[PlannedEntry, ...] = ()
```

Add after the `CleanupEvent` alias:

```python
# Sees every event before the adapter answers it; presentation only (spec §3.1).
CleanupObserver = Callable[[CleanupEvent], None]


def _notify_observer(on_event: CleanupObserver | None, event: CleanupEvent) -> None:
    """Deliver one event; an observer that raises is logged and can never alter a run."""
    if on_event is None:
        return
    try:
        on_event(event)
    except Exception:
        logger.warning("cleanup observer failed on %s", type(event).__name__, exc_info=True)
```

Add a helper used by both the plan and execution (replace the inline `worktrees_first = sorted(...)` in `_iter_execute` with a call to it):

```python
def _execution_order(
    selections: list[tuple[Entry, SelectionState]],
) -> list[tuple[Entry, SelectionState]]:
    """Approved reclaimable worktrees first (spec §6.4); otherwise selection order."""
    return sorted(
        selections,
        key=lambda item: not (item[1] == "approved" and is_reclaimable_worktree(item[0])),
    )


def _build_plan(selections: list[tuple[Entry, SelectionState]]) -> tuple[PlannedEntry, ...]:
    return tuple(
        PlannedEntry(
            entry=entry,
            actions=tuple(entry.cleanup_actions()),
            estimate_bytes=entry.reclaimable_bytes,
        )
        for entry, state in _execution_order(selections)
        if state == "approved"
    )
```

In `iter_cleanup_events`, build the confirm event with the plan:

```python
    confirmed = yield ConfirmRequired(
        approved=approved,
        total_bytes=total_bytes,
        unknown_entries=unknown_entries,
        plan=_build_plan(selections),
    )
```

In `run()` and `run_async()`: add the keyword `on_event: CleanupObserver | None = None` after `verify`, and call `_notify_observer(on_event, event)` as the first statement inside the `while True:` loop body (before the `isinstance` chain), so every event is observed exactly once before it is answered.

Replace `_confirm_summary`:

```python
def _confirm_summary(event: ConfirmRequired) -> str:
    summary = f"Execute these {len(event.approved)} entries (~{human_bytes(event.total_bytes)} estimated"
    if event.unknown_entries:
        summary += f", +{event.unknown_entries} unknown"
    return summary + ")?"
```

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra web pytest tests/test_cleanup.py tests/web -q`
Expected: all pass (the web runner still calls `_confirm_summary` and ignores `plan`).

- [ ] **Step 5: Lint, types, commit**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format src tests && uv run --extra dev --extra web mypy`

```bash
git add src/devdoctor/cleanup.py tests/test_cleanup.py
git commit -m "feat(cleanup): observe every event and carry the plan on the confirm

run() and run_async() accept an on_event observer that sees each event before
it is answered and can never alter a run; ConfirmRequired lists the approved
entries in execution order with the actions that will run (#126).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Shared audit event builder, used by the web runner

**Files:**
- Create: `src/devdoctor/cleanup_audit.py`
- Modify: `src/devdoctor/web/cleanup_runner.py` (`run()` ~line 52–120; `_write_audit` ~line 123–168; `_estimated_reclaimed_bytes`/`_all_bytes_verified` ~line 170–180)
- Test: `tests/test_cleanup_audit.py` (create); `tests/web/test_cleanup_runner.py` (append; create if absent with the imports shown)

**Interfaces:**
- Consumes: `PlannedEntry` (Task 2), `CleanResult`, `Entry`, `estimated_reclaimable_bytes` from `devdoctor.types`.
- Produces (used by Task 5):
  ```python
  def estimated_reclaimed_bytes(entries: Sequence[Entry], results: Sequence[CleanResult]) -> int
  def all_bytes_verified(results: Sequence[CleanResult]) -> bool
  def build_event(results, outcome, *, source: Literal["cli", "web"], plan: Sequence[PlannedEntry],
                  entries: Sequence[Entry], job_id: str | None = None, error: str | None = None,
                  free_before: int | None = None, free_after: int | None = None,
                  now: datetime | None = None) -> dict[str, Any]
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cleanup_audit.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from devdoctor.cleanup import PlannedEntry
from devdoctor.cleanup_audit import all_bytes_verified, build_event, estimated_reclaimed_bytes
from devdoctor.types import CleanResult, DeletePathAction, Entry, Risk


def _entry(id_: str, size: int, provider: str = "p") -> Entry:
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[f"rm -rf /{id_}"],
    )


def _plan(*entries: Entry) -> list[PlannedEntry]:
    return [
        PlannedEntry(entry=e, actions=(DeletePathAction(e.path, recursive=True),), estimate_bytes=e.size_bytes)
        for e in entries
    ]


def test_build_event_keeps_the_existing_keys_and_adds_the_new_ones() -> None:
    a, b, c = _entry("a", 100), _entry("b", 200), _entry("c", 300)
    results = [
        CleanResult(entry_id="a", status="ok", freed_bytes=100, message="cleanup succeeded"),
        CleanResult(entry_id="b", status="error", freed_bytes=0, message="rm: boom"),
        CleanResult(entry_id="c", status="skipped", freed_bytes=0, message="declined"),
    ]
    at = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)

    event = build_event(
        results, "ok", source="cli", plan=_plan(a, b), entries=[a, b, c],
        free_before=10_000, free_after=10_100, now=at,
    )

    assert event["type"] == "cleanup"
    assert event["source"] == "cli"
    assert event["job_id"] is None
    assert event["outcome"] == "ok"
    assert event["at"] == "2026-09-16T13:00:00+00:00"
    assert event["total_freed_bytes"] == 100
    assert event["total_estimated_reclaimed_bytes"] == 100
    assert event["bytes_verified"] is False
    assert event["free_before_bytes"] == 10_000
    assert event["free_after_bytes"] == 10_100
    assert event["plan"] == [
        {"entry_id": "a", "provider": "p", "label": "p/a", "path": "/a", "risk": "safe",
         "estimate_bytes": 100, "actions": ["rm -rf -- /a"]},
        {"entry_id": "b", "provider": "p", "label": "p/b", "path": "/b", "risk": "safe",
         "estimate_bytes": 200, "actions": ["rm -rf -- /b"]},
    ]
    assert event["results"][1] == {
        "entry_id": "b", "status": "error", "freed_bytes": 0, "message": "rm: boom",
        "bytes_verified": False, "provider": "p", "label": "p/b", "path": "/b",
    }
    assert "error" not in event


def test_build_event_for_a_web_run_carries_job_id_and_error() -> None:
    a = _entry("a", 100)
    event = build_event([], "error", source="web", plan=[], entries=[a], job_id="abc", error="boom")
    assert (event["source"], event["job_id"], event["error"]) == ("web", "abc", "boom")
    assert event["free_before_bytes"] is None and event["free_after_bytes"] is None
    assert event["plan"] == [] and event["results"] == []


def test_totals_count_only_successful_entries() -> None:
    a, b = _entry("a", 100), _entry("b", 200)
    results = [
        CleanResult(entry_id="a", status="ok", freed_bytes=100, bytes_verified=True),
        CleanResult(entry_id="b", status="error", freed_bytes=0),
    ]
    assert estimated_reclaimed_bytes([a, b], results) == 100
    assert all_bytes_verified(results) is True
    assert all_bytes_verified([CleanResult(entry_id="b", status="error", freed_bytes=0)]) is False
```

Append to `tests/web/test_cleanup_runner.py` (create the file with `from devdoctor.storage import build_storage` etc. if it does not exist; otherwise reuse its runner fixture). The test drives a runner end to end the way the existing runner tests do, then reads the audit back:

```python
async def test_web_audit_event_names_its_source_and_plan(tmp_path, monkeypatch):
    # Build a runner exactly as the existing lifecycle tests in this file do (one
    # safe entry, run_line returning ShellResult(0, "", ""), yes_safe=True, and a
    # confirm answered True); then:
    events = build_storage().read_audit_events(limit=1)
    assert events[0]["source"] == "web"
    assert events[0]["job_id"] == runner.id
    assert [p["entry_id"] for p in events[0]["plan"]] == [entry.id]
    assert events[0]["results"][0]["provider"] == entry.provider
```

Fill in the runner construction from the nearest existing test in that file (or from `tests/web/test_routes_clean.py::test_full_clean_job_lifecycle_via_sse` if the runner file does not exist — in that case assert the same keys after the lifecycle test's `done` event, reading through `build_storage()`), keeping `runner` and `entry` as the names the assertions use.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_cleanup_audit.py tests/web/test_cleanup_runner.py -q`
Expected: `ModuleNotFoundError: No module named 'devdoctor.cleanup_audit'`, and the web test failing on `KeyError: 'source'`.

- [ ] **Step 3: Implement**

Create `src/devdoctor/cleanup_audit.py`:

```python
"""The audit record of one cleanup run, shared by the CLI and the web runner (spec §5.1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from devdoctor.cleanup import PlannedEntry
from devdoctor.types import CleanResult, Entry, estimated_reclaimable_bytes

AUDIT_TYPE = "cleanup"


def estimated_reclaimed_bytes(entries: Sequence[Entry], results: Sequence[CleanResult]) -> int:
    successful = {r.entry_id for r in results if r.status == "ok"}
    return estimated_reclaimable_bytes([e for e in entries if e.id in successful])


def all_bytes_verified(results: Sequence[CleanResult]) -> bool:
    successful = [r for r in results if r.status == "ok"]
    return bool(successful) and all(r.bytes_verified for r in successful)


def build_event(
    results: Sequence[CleanResult],
    outcome: str,
    *,
    source: Literal["cli", "web"],
    plan: Sequence[PlannedEntry],
    entries: Sequence[Entry],
    job_id: str | None = None,
    error: str | None = None,
    free_before: int | None = None,
    free_after: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    by_id = {e.id: e for e in entries}
    estimated = estimated_reclaimed_bytes(entries, results)
    event: dict[str, Any] = {
        "type": AUDIT_TYPE,
        "source": source,
        "job_id": job_id,
        "at": (now or datetime.now(UTC)).isoformat(),
        "outcome": outcome,
        # Compatibility key for audit readers written before explicit estimate semantics.
        "total_freed_bytes": estimated,
        "total_estimated_reclaimed_bytes": estimated,
        "bytes_verified": all_bytes_verified(results),
        "free_before_bytes": free_before,
        "free_after_bytes": free_after,
        "plan": [
            {
                "entry_id": p.entry.id,
                "provider": p.entry.provider,
                "label": p.entry.label,
                "path": None if p.entry.path is None else str(p.entry.path),
                "risk": p.entry.risk.value,
                "estimate_bytes": p.estimate_bytes,
                "actions": list(p.lines),
            }
            for p in plan
        ],
        "results": [
            {
                "entry_id": r.entry_id,
                "status": r.status,
                "freed_bytes": r.freed_bytes,
                "message": r.message,
                "bytes_verified": r.bytes_verified,
                "provider": _field(by_id.get(r.entry_id), "provider"),
                "label": _field(by_id.get(r.entry_id), "label"),
                "path": _path(by_id.get(r.entry_id)),
            }
            for r in results
        ],
    }
    if error is not None:
        event["error"] = error
    return event


def _field(entry: Entry | None, name: str) -> str | None:
    return None if entry is None else str(getattr(entry, name))


def _path(entry: Entry | None) -> str | None:
    return None if entry is None or entry.path is None else str(entry.path)
```

`Risk` is a `StrEnum`-like enum in `devdoctor.types`; if `.value` is not the lowercase name, use whatever `Report.to_json` uses for `risk`.

In `src/devdoctor/web/cleanup_runner.py`:
- import `from devdoctor import cleanup_audit`;
- add a field `_plan: tuple[cleanup_mod.PlannedEntry, ...] = ()`;
- in `run()`'s `ConfirmRequired` branch, before computing the summary, add `self._plan = event.plan`;
- replace the body of `_write_audit` so it builds the payload with
  `cleanup_audit.build_event(results, outcome, source="web", plan=self._plan, entries=self.report.entries, job_id=self.id, error=error)` and keeps the existing storage/history_log write and the `except Exception` warning;
- replace `_estimated_reclaimed_bytes` and `_all_bytes_verified` with calls to `cleanup_audit.estimated_reclaimed_bytes(self.report.entries, results)` / `cleanup_audit.all_bytes_verified(results)` where they are used (the `done` event payload), and delete the two methods.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra web pytest tests/test_cleanup_audit.py tests/web -q`
Expected: all pass.

- [ ] **Step 5: Lint, types, commit**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format src tests && uv run --extra dev --extra web mypy`

```bash
git add src/devdoctor/cleanup_audit.py src/devdoctor/web/cleanup_runner.py tests/test_cleanup_audit.py tests/web/test_cleanup_runner.py
git commit -m "feat: build the cleanup audit record in one place

cleanup_audit.build_event keeps every key the web wizard wrote and adds the
source, the plan, per-entry provider/label/path and the free-space delta;
the web runner uses it (#126).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `CleanupPresenter`

**Files:**
- Modify: `src/devdoctor/rendering.py` (add the presenter; delete `real_prompts` ~line 130–159)
- Test: `tests/test_rendering.py` (create, or append if it exists)

**Interfaces:**
- Consumes: `PlannedEntry`, `ConfirmRequired`, `ExecuteStep`, `EntryResolved`, `PromptRequired`, `CleanupEvent` (Task 2); `ScanStarted`/`ProviderStarted`/`ProviderFinished` from `devdoctor.discovery`; `human_bytes`/`estimated_bytes` (Task 1).
- Produces (used by Task 5):
  ```python
  class CleanupPresenter:
      def __init__(self, console: Console, *, home: Path | None = None) -> None
      @contextmanager
      def scanning(self) -> Iterator[None]                 # spinner updated by scan_progress
      def scan_progress(self, event: ScanProgressEvent) -> None
      @contextmanager
      def executing(self) -> Iterator[None]                # spinner updated by ExecuteStep
      def on_event(self, event: CleanupEvent) -> None
      def prompt_choice(self, entry: Entry) -> Choice
      def confirm(self, message: str) -> bool
      def summary(self, results: Sequence[CleanResult], *, free_before: int | None, free_after: int | None) -> None
      plan: tuple[PlannedEntry, ...]                        # captured from ConfirmRequired
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rendering.py`:

```python
from pathlib import Path

from rich.console import Console

from devdoctor.cleanup import ConfirmRequired, EntryResolved, ExecuteStep, PlannedEntry
from devdoctor.discovery import ProviderFinished, ProviderStarted, ScanStarted
from devdoctor.rendering import CleanupPresenter
from devdoctor.types import AdviceAction, CleanResult, DeletePathAction, Entry, ProviderTiming, Risk

HOME = Path("/Users/me")


def _console() -> Console:
    return Console(record=True, width=140, force_terminal=False, color_system=None)


def _entry(id_: str, size: int | None, risk: Risk = Risk.SAFE, provider: str = "uv-cache") -> Entry:
    path = HOME / ".cache" / id_
    return Entry(
        provider=provider,
        id=id_,
        path=path,
        label=str(path),
        size_bytes=size or 0,
        mtime=None,
        risk=risk,
        recipe=[],
        actions=(DeletePathAction(path, recursive=True),),
    )


def _planned(entry: Entry, estimate: int | None = None) -> PlannedEntry:
    est = entry.size_bytes if estimate is None else estimate
    return PlannedEntry(entry=entry, actions=entry.actions, estimate_bytes=est)


def test_plan_table_lists_every_entry_with_human_sizes_and_the_command() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    uv = _entry("uv", 5_600_000_000)
    hint = _entry("hint", 0, provider="docker-vm-disk", risk=Risk.RECLAIMABLE)
    hint = Entry(**{**hint.__dict__, "actions": (AdviceAction("shrink the disk image"),)})
    p.on_event(EntryResolved(CleanResult(entry_id="x", status="skipped", freed_bytes=0,
                                         message="dangerous (pass --allow-dangerous to include)")))
    p.on_event(ConfirmRequired(approved=[uv, hint], total_bytes=5_600_000_000, unknown_entries=1,
                               plan=(_planned(uv), _planned(hint, None))))

    out = console.export_text()
    assert "Cleanup plan — 2 entries, ~5.2G estimated (+1 unknown)" in out
    assert "uv-cache" in out and "~/.cache/uv" in out and "5.2G" in out
    assert "rm -rf -- /Users/me/.cache/uv" in out
    assert "docker-vm-disk" in out and "unknown" in out and "echo 'shrink the disk image'" in out
    assert "Not in this run: 1 dangerous (pass --allow-dangerous)" in out
    assert p.plan[0].entry.id == "uv"


def test_progress_lines_show_status_and_the_failure_reason() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    uv, pip = _entry("uv", 5_600_000_000), _entry("pip", 700_000_000, provider="pip-cache")
    p.on_event(ConfirmRequired(approved=[uv, pip], total_bytes=6_300_000_000,
                               plan=(_planned(uv), _planned(pip))))
    p.on_event(ExecuteStep(entry=uv, action=uv.actions[0]))
    p.on_event(EntryResolved(CleanResult(entry_id="uv", status="error", freed_bytes=0,
                                         message="error: failed to clean\nsecond line")))
    p.on_event(EntryResolved(CleanResult(entry_id="pip", status="ok", freed_bytes=700_000_000,
                                         message="cleanup succeeded; byte count is an estimate")))

    out = console.export_text()
    assert "[1/2] ✗ uv-cache" in out and "failed: error: failed to clean" in out
    assert "second line" not in out
    assert "[2/2] ✓ pip-cache" in out and "~667.6M" in out


def test_summary_states_estimates_and_the_free_space_delta() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    uv, pip = _entry("uv", 5_600_000_000), _entry("pip", 700_000_000, provider="pip-cache")
    p.on_event(ConfirmRequired(approved=[uv, pip], total_bytes=6_300_000_000,
                               plan=(_planned(uv), _planned(pip))))
    results = [
        CleanResult(entry_id="uv", status="error", freed_bytes=0, message="boom"),
        CleanResult(entry_id="pip", status="ok", freed_bytes=700_000_000),
        CleanResult(entry_id="x", status="skipped", freed_bytes=0, message="declined"),
    ]
    p.summary(results, free_before=70_000_000_000, free_after=70_500_000_000)

    out = console.export_text()
    assert "Done: 1 ok · 1 failed · 1 skipped" in out
    assert "~667.6M estimated reclaimed of ~5.9G planned" in out
    assert "free space 65.2G → 65.7G (+476.8M)" in out
    assert "APFS local snapshots can hold freed blocks" in out
    assert "recorded: devdoctor history" in out


def test_summary_omits_the_snapshot_hint_when_space_was_freed() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    pip = _entry("pip", 700_000_000, provider="pip-cache")
    p.on_event(ConfirmRequired(approved=[pip], total_bytes=700_000_000, plan=(_planned(pip),)))
    p.summary([CleanResult(entry_id="pip", status="ok", freed_bytes=700_000_000)],
              free_before=1_000_000_000, free_after=1_700_000_000)
    out = console.export_text()
    assert "APFS" not in out and "free space" in out


def test_summary_without_disk_figures_omits_the_delta() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    p.on_event(ConfirmRequired(approved=[], total_bytes=0, plan=()))
    p.summary([], free_before=None, free_after=None)
    out = console.export_text()
    assert "Done: 0 ok · 0 failed · 0 skipped" in out and "free space" not in out


def test_scan_progress_updates_the_spinner_text() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    with p.scanning():
        p.scan_progress(ScanStarted(providers=("a", "b", "c", "d")))
        p.scan_progress(ProviderStarted("a"))
        p.scan_progress(ProviderStarted("b"))
        assert p.status_text == "scanning… 0/4 providers · running: a, b"
        p.scan_progress(ProviderFinished(ProviderTiming(name="a", bytes=1, entries=1, duration_ms=1)))
        assert p.status_text == "scanning… 1/4 providers · running: b"


def test_control_characters_never_reach_the_console() -> None:
    console = _console()
    p = CleanupPresenter(console, home=HOME)
    evil = _entry("x\x1b]0;pwned\x07y", 10)
    p.on_event(ConfirmRequired(approved=[evil], total_bytes=10, plan=(_planned(evil),)))
    assert "\x1b" not in console.export_text()
```

Adjust the three `~…` figures to what `human_bytes` renders if they differ (`700_000_000` → `667.6M`, `6_300_000_000` → `5.9G`, `500_000_000` → `476.8M`, `70_000_000_000` → `65.2G`, `70_500_000_000` → `65.7G` are the 1024-based values).

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_rendering.py -q`
Expected: `ImportError: cannot import name 'CleanupPresenter'`.

- [ ] **Step 3: Implement**

In `src/devdoctor/rendering.py` add the imports (`from collections.abc import Sequence`, `from pathlib import Path`, `from rich.status import Status`, `from devdoctor.cleanup import CleanupEvent, ConfirmRequired, EntryResolved, ExecuteStep, PlannedEntry, PromptRequired`, `from devdoctor.discovery import ProviderFinished, ProviderStarted, ScanProgressEvent, ScanStarted`, `from devdoctor.types import CleanResult`) and the class:

```python
_MAX_RUNNING_NAMES = 3
_SNAPSHOT_HINT = (
    "APFS local snapshots can hold freed blocks; "
    'see docs "why did my free space not change"'
)


class CleanupPresenter:
    """Every line `devdoctor clean` prints, driven by cleanup and scan events (spec §4).

    It only observes: a failure here is logged by the core and the run continues.
    """

    def __init__(self, console: Console, *, home: Path | None = None) -> None:
        self._console = console
        self._home = home or Path.home()
        self._status: Status | None = None
        self.status_text = ""
        self.plan: tuple[PlannedEntry, ...] = ()
        self._index: dict[str, int] = {}
        self._pre_skipped: list[CleanResult] = []
        self._scan_total = 0
        self._scan_done = 0
        self._scan_running: list[str] = []

    # -- scan phase -------------------------------------------------------

    @contextmanager
    def scanning(self) -> Iterator[None]:
        self._set_status("scanning…")
        try:
            yield
        finally:
            self._clear_status()

    def scan_progress(self, event: ScanProgressEvent) -> None:
        if isinstance(event, ScanStarted):
            self._scan_total, self._scan_done, self._scan_running = len(event.providers), 0, []
        elif isinstance(event, ProviderStarted):
            self._scan_running.append(event.name)
        elif isinstance(event, ProviderFinished):
            self._scan_done += 1
            if event.timing.name in self._scan_running:
                self._scan_running.remove(event.timing.name)
        if self._scan_total and self._scan_done == self._scan_total:
            self._set_status("scanning… reconciling")
            return
        text = f"scanning… {self._scan_done}/{self._scan_total} providers"
        if self._scan_running:
            names = ", ".join(self._scan_running[:_MAX_RUNNING_NAMES])
            more = len(self._scan_running) - _MAX_RUNNING_NAMES
            text += f" · running: {names}" + (f" +{more}" if more > 0 else "")
        self._set_status(text)

    # -- cleanup events ---------------------------------------------------

    @contextmanager
    def executing(self) -> Iterator[None]:
        self._set_status("cleaning…")
        try:
            yield
        finally:
            self._clear_status()

    def on_event(self, event: CleanupEvent) -> None:
        if isinstance(event, ConfirmRequired):
            self.plan = event.plan
            self._index = {p.entry.id: i + 1 for i, p in enumerate(event.plan)}
            self._print_plan(event)
        elif isinstance(event, ExecuteStep):
            n = self._index.get(event.entry.id, 0)
            self._set_status(f"[{n}/{len(self.plan)}] running: {_strip_controls(event.line)}")
        elif isinstance(event, EntryResolved):
            if not self.plan:
                self._pre_skipped.append(event.result)
            elif event.result.entry_id in self._index:
                self._print_result(event.result)
        # PromptRequired and VerifyRequired need no output here.

    def _print_plan(self, event: ConfirmRequired) -> None:
        total = len(event.plan)
        title = f"Cleanup plan — {total} entries, ~{_human_bytes(event.total_bytes)} estimated"
        if event.unknown_entries:
            title += f" (+{event.unknown_entries} unknown)"
        table = Table(title=title, show_lines=False)
        table.add_column("#", justify="right")
        table.add_column("provider", style="cyan")
        table.add_column("risk", justify="center")
        table.add_column("est.", justify="right")
        table.add_column("path", overflow="fold")
        table.add_column("action", overflow="ellipsis")
        for i, planned in enumerate(event.plan, 1):
            lines = planned.lines
            action = lines[0] if lines else "(no cleanup action)"
            if len(lines) > 1:
                action += f" (+{len(lines) - 1} more)"
            table.add_row(
                str(i),
                _safe_cell(planned.entry.provider),
                _risk_label(planned.entry.risk),
                _estimated_bytes(planned.estimate_bytes).lstrip("~"),
                _safe_cell(self._short_path(planned.entry)),
                _safe_cell(action),
            )
        self._console.print(table)
        skipped = self._skipped_summary()
        if skipped:
            self._console.print(Text(f"Not in this run: {skipped}", style="dim"))

    def _skipped_summary(self) -> str:
        counts: dict[str, int] = {}
        for r in self._pre_skipped:
            counts[r.message or "skipped"] = counts.get(r.message or "skipped", 0) + 1
        return ", ".join(f"{n} {_strip_controls(msg)}" for msg, n in counts.items())

    def _print_result(self, result: CleanResult) -> None:
        n = self._index[result.entry_id]
        planned = self.plan[n - 1]
        mark = {"ok": "✓", "error": "✗", "skipped": "–"}.get(result.status, "·")
        if result.status == "skipped" and result.message == "advice only; no command executed":
            mark = "·"
        first_line = (result.message or "").splitlines()[0] if result.message else ""
        detail = {
            "ok": f"~{_human_bytes(result.freed_bytes)}" if result.freed_bytes else "done",
            "error": f"failed: {first_line}",
            "skipped": first_line if mark == "·" else f"skipped: {first_line}",
        }.get(result.status, first_line)
        line = Text(f"[{n}/{len(self.plan)}] {mark} ")
        line.append(_strip_controls(planned.entry.provider).ljust(22))
        line.append(_strip_controls(self._short_path(planned.entry)).ljust(40) + "  ")
        line.append(_strip_controls(detail))
        self._console.print(line)

    # -- prompts ------------------------------------------------------------

    def prompt_choice(self, entry: Entry) -> Choice:
        header = Text()
        header.append(_strip_controls(entry.provider), style="bold")
        header.append(
            f" — {_strip_controls(entry.label)}  "
            f"(footprint={_human_bytes_or_unknown(entry.footprint_bytes)}, "
            f"estimated reclaimable={_estimated_bytes(entry.reclaimable_bytes)}, "
            f"risk={_risk_label(entry.risk)})"
        )
        self._console.print(header)
        recipes = entry.recipe_lines()
        recipe_hint = _strip_controls(recipes[0]) if recipes else "(no cleanup action)"
        self._console.print(Text(f"  → {recipe_hint}"))
        raw = Prompt.ask(
            "[y]es / [n]o / [a]ll-in-provider / [s]kip-provider / [q]uit",
            console=self._console,
            choices=["y", "n", "a", "s", "q"],
            default="n",
            show_choices=False,
        )
        return raw  # type: ignore[return-value]

    def confirm(self, message: str) -> bool:
        return RichConfirm.ask(message, console=self._console, default=False)

    # -- summary --------------------------------------------------------------

    def summary(
        self,
        results: Sequence[CleanResult],
        *,
        free_before: int | None,
        free_after: int | None,
    ) -> None:
        ok = sum(r.status == "ok" for r in results)
        failed = sum(r.status == "error" for r in results)
        skipped = len(results) - ok - failed
        reclaimed = sum(r.freed_bytes for r in results if r.status == "ok")
        planned = sum(p.estimate_bytes or 0 for p in self.plan)
        self._console.print(
            Text(
                f"Done: {ok} ok · {failed} failed · {skipped} skipped — "
                f"~{_human_bytes(reclaimed)} estimated reclaimed of ~{_human_bytes(planned)} planned",
                style="bold",
            )
        )
        tail = ""
        if free_before is not None and free_after is not None:
            delta = free_after - free_before
            sign = "+" if delta >= 0 else "-"
            tail = (
                f"free space {_human_bytes(free_before)} → {_human_bytes(free_after)} "
                f"({sign}{_human_bytes(abs(delta))}) · "
            )
        self._console.print(Text(f"{tail}recorded: devdoctor history"))
        if free_before is not None and free_after is not None and reclaimed:
            if free_after - free_before < reclaimed / 2:
                self._console.print(Text(_SNAPSHOT_HINT, style="yellow"))

    # -- helpers ---------------------------------------------------------------

    def _short_path(self, entry: Entry) -> str:
        if entry.path is None:
            return entry.label
        text = str(entry.path)
        home = str(self._home)
        return "~" + text[len(home):] if text == home or text.startswith(home + "/") else text

    def _set_status(self, text: str) -> None:
        self.status_text = text
        if self._status is None:
            self._status = self._console.status(text)
            self._status.start()
        else:
            self._status.update(text)

    def _clear_status(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None
```

Delete `real_prompts` (its only caller is `cli.py`, rewired in Task 5; check `grep -rn real_prompts src tests` and update any test that imports it to use `CleanupPresenter(console).prompt_choice`). `Choice` is already imported in the module.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra web pytest tests/test_rendering.py -q`
Expected: all pass. If a `~…` figure differs, fix the test's expected string to `human_bytes`' real output — never the formatter.

- [ ] **Step 5: Lint, types, commit**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format src tests && uv run --extra dev --extra web mypy`

```bash
git add src/devdoctor/rendering.py tests/test_rendering.py
git commit -m "feat(cli): a presenter that shows the plan, progress and summary of a cleanup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `clean` wiring, `--yes`/`--risk`, audit write, and `history`

**Files:**
- Modify: `src/devdoctor/cli.py` (`clean` ~line 184–226; imports; new `history` command after `providers`)
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `CleanupPresenter` (Task 4), `cleanup_audit.build_event` (Task 3), `run(..., on_event=)` (Task 2), `human_bytes` (Task 1), `build_storage`/`load_app_settings` (`devdoctor.storage`, `devdoctor.config`), `discovery.scan(on_progress=)`.
- Produces: `devdoctor clean [--provider P]* [--risk R]* [--execute] [--yes-safe] [--yes] [--allow-dangerous]`; `devdoctor history [--limit N] [--json] [REF]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
import sys
from pathlib import Path

from devdoctor.storage import build_storage
from devdoctor.types import ShellResult


def _fixture(tmp_path: Path, monkeypatch) -> Path:
    """A YAML provider with one safe cache; returns the cache path."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "blob.bin").write_bytes(b"x" * 4096)
    yaml = tmp_path / "p.yaml"
    yaml.write_text(
        f"""- name: sample-cache
  description: sample
  risk: safe
  platforms: [darwin, linux]
  paths: ["{cache}"]
  recipe: "rm -rf {{path}}"
"""
    )
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    return cache


def test_clean_execute_prints_plan_progress_failure_and_records_the_run(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    shell = FakeShell(
        which_table={"ollama": None, "docker": None},
        responses={("rm", "-rf", "--", str(cache)): ShellResult(1, "", "rm: cannot remove: boom")},
    )
    result = CliRunner().invoke(
        build_cli(shell), ["clean", "--execute", "--yes-safe", "--yes", "--provider", "sample-cache"]
    )

    assert result.exit_code == 2, result.output
    assert "Cleanup plan — 1 entries" in result.output
    assert "sample-cache" in result.output and "rm -rf --" in result.output
    assert "[1/1] ✗ sample-cache" in result.output
    assert "failed: rm: cannot remove: boom" in result.output
    assert "Done: 0 ok · 1 failed · 0 skipped" in result.output
    assert "bytes" not in result.output.split("Done:")[1]

    (event,) = build_storage().read_audit_events(limit=1)
    assert event["source"] == "cli" and event["outcome"] == "ok"
    assert event["results"][0]["status"] == "error"
    assert event["results"][0]["message"] == "rm: cannot remove: boom"
    assert event["plan"][0]["provider"] == "sample-cache"
    assert isinstance(event["free_before_bytes"], int)


def test_clean_execute_without_a_tty_and_without_yes_aborts_before_running(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    result = CliRunner().invoke(build_cli(shell), ["clean", "--execute", "--yes-safe"])

    assert result.exit_code != 0
    assert "no terminal to confirm on; pass --yes to run unattended" in result.output
    assert shell.calls == []
    assert cache.exists()


def test_clean_risk_filter_scopes_the_run(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    result = CliRunner().invoke(
        build_cli(shell), ["clean", "--execute", "--yes-safe", "--yes", "--risk", "dangerous"]
    )
    assert result.exit_code == 0, result.output
    assert "Cleanup plan" not in result.output
    assert shell.calls == []
    assert cache.exists()


def test_history_lists_runs_and_shows_one(tmp_path, monkeypatch):
    cache = _fixture(tmp_path, monkeypatch)
    shell = FakeShell(
        which_table={"ollama": None, "docker": None},
        responses={("rm", "-rf", "--", str(cache)): ShellResult(0, "", "")},
    )
    runner = CliRunner()
    assert runner.invoke(build_cli(shell), ["clean", "--execute", "--yes-safe", "--yes"]).exit_code == 0

    listing = runner.invoke(build_cli(shell), ["history"])
    assert listing.exit_code == 0, listing.output
    assert "cli" in listing.output and "1 ok" in listing.output and "~4.0K" in listing.output

    detail = runner.invoke(build_cli(shell), ["history", "1"])
    assert detail.exit_code == 0, detail.output
    assert "sample-cache" in detail.output and "ok" in detail.output
    assert "rm -rf --" in detail.output

    as_json = runner.invoke(build_cli(shell), ["history", "--json"])
    assert as_json.exit_code == 0
    assert json.loads(as_json.output)[0]["source"] == "cli"


def test_history_with_no_runs_says_so(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    result = CliRunner().invoke(build_cli(FakeShell()), ["history"])
    assert result.exit_code == 0
    assert "no cleanup runs recorded" in result.output


def test_clean_help_describes_every_option(tmp_path, monkeypatch):
    result = CliRunner().invoke(build_cli(FakeShell()), ["clean", "--help"])
    assert result.exit_code == 0
    for flag in ("--provider", "--risk", "--execute", "--yes-safe", "--yes", "--allow-dangerous"):
        assert flag in result.output
    assert "plan still prints" in result.output
```

The `_fixture` YAML mirrors `tests/web/test_routes_dashboard.py::_client`; the sample cache's `size_bytes` is 4096, which `human_bytes` renders as `4.0K`. `CliRunner` stdin is never a TTY, hence the `isatty` monkeypatch.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_cli.py -k "clean_execute or clean_risk or history or clean_help" -q`
Expected: failures — `no such option: --yes`, `no such option: --risk`, `No such command 'history'`, and the help test missing `--risk`/`--yes`.

- [ ] **Step 3: Implement**

In `src/devdoctor/cli.py`:

Imports to add: `import shutil`, `from devdoctor import cleanup_audit`, `from devdoctor.config import load_app_settings`, `from devdoctor.rendering import CleanupPresenter, render_history, render_history_run` (the two renderers are defined in Step 3b below), `from devdoctor.storage import build_storage`, `from devdoctor.units import human_bytes`; remove `real_prompts` from the rendering import.

Replace the `clean` command:

```python
    @cli.command()
    @click.option("--provider", "providers", multiple=True, help="Limit to these providers.")
    @click.option(
        "--risk",
        "risk",
        multiple=True,
        help="Include only these risks (safe, reclaimable, dangerous; repeatable or comma-separated).",
    )
    @click.option("--execute", is_flag=True, help="Run the cleanup. Without it, preview only.")
    @click.option(
        "--yes-safe", is_flag=True, help="Approve safe entries without a per-entry prompt."
    )
    @click.option(
        "--yes",
        "yes_all",
        is_flag=True,
        help="Skip the final confirmation; the plan still prints. For scripts and agents.",
    )
    @click.option(
        "--allow-dangerous",
        is_flag=True,
        help="Offer dangerous entries too (they are skipped otherwise).",
    )
    @click.pass_context
    def clean(  # noqa: PLR0913
        ctx: click.Context,
        providers: tuple[str, ...],
        risk: tuple[str, ...],
        execute: bool,
        yes_safe: bool,
        yes_all: bool,
        allow_dangerous: bool,
    ) -> None:
        """Clean up caches found by a scan: preview by default, act with --execute."""
        if execute and not yes_all and not sys.stdin.isatty():
            raise click.ClickException("no terminal to confirm on; pass --yes to run unattended")
        providers_list = registry.load_providers(ctx.obj["shell"])
        filters = ScanFilters(
            risks=_parse_risks(risk),
            providers=frozenset(providers) if providers else None,
        )
        console = Console()
        presenter = CleanupPresenter(console)
        with presenter.scanning():
            report = discovery.scan(
                providers_list, filters, datetime.now(UTC), on_progress=presenter.scan_progress
            )
        if not execute:
            render_report_table(console, report)
            console.print("[dim]Preview only — re-run with --execute to perform cleanup.[/]")
            return
        free_before = _free_bytes()
        with presenter.executing():
            results = cleanup_run(
                report,
                shell=ctx.obj["shell"],
                prompt_choice=presenter.prompt_choice,
                confirm=(lambda _message: True) if yes_all else presenter.confirm,
                opts=CleanupOpts(
                    execute=True,
                    yes_safe=yes_safe,
                    allow_dangerous=allow_dangerous,
                    providers=frozenset(providers) if providers else None,
                ),
                # Re-check each worktree immediately before removing it (#110).
                verify=GitWorktreeProvider(ctx.obj["shell"]).verify_removable,
                on_event=presenter.on_event,
            )
        free_after = _free_bytes()
        presenter.summary(results, free_before=free_before, free_after=free_after)
        _record_run(report, presenter, results, free_before, free_after)
        if any(r.status == "error" for r in results):
            sys.exit(2)
```

The spinner from `presenter.executing()` shows `[n/N] running: …` between result lines; `console.status` and printed lines coexist in Rich. If the per-entry `Prompt.ask` misbehaves inside an active status spinner, stop the status around prompts: in the presenter's `on_event`, call `self._clear_status()` when a `PromptRequired` arrives and `_set_status("cleaning…")` on the next `ExecuteStep` — note this in the task report if you needed it.

Add module-level helpers (next to `_parse_risks`):

```python
def _free_bytes() -> int | None:
    """Free bytes on the volume holding the home directory; None when unavailable."""
    try:
        return shutil.disk_usage(Path.home()).free
    except OSError:
        return None


def _record_run(
    report: Report,
    presenter: CleanupPresenter,
    results: list[CleanResult],
    free_before: int | None,
    free_after: int | None,
) -> None:
    """Append the run to the audit log the web UI shares; never fails the run."""
    try:
        event = cleanup_audit.build_event(
            results,
            "ok",
            source="cli",
            plan=presenter.plan,
            entries=report.entries,
            free_before=free_before,
            free_after=free_after,
        )
        build_storage(load_app_settings()).append_audit_event(event)
    except Exception:
        logging.getLogger(__name__).warning(
            "cleanup audit write failed; run not recorded", exc_info=True
        )
```

(`Report` and `CleanResult` come from `devdoctor.types`; add them to the existing import. `outcome` is `"ok"` for a completed run — a run that reaches the summary completed; failed entries are in `results`.)

Add the `history` command after `providers`:

```python
    @cli.command()
    @click.argument("ref", required=False)
    @click.option("--limit", default=20, show_default=True, help="Runs to list.")
    @click.option("--json", "json_out", is_flag=True, help="Emit the raw audit events.")
    @click.pass_context
    def history(ctx: click.Context, ref: str | None, limit: int, json_out: bool) -> None:
        """Past cleanup runs: list them, or show one by number (1 = newest) or web job id."""
        del ctx
        events = [
            e
            for e in build_storage(load_app_settings()).read_audit_events(limit=None)
            if e.get("type") == "cleanup"
        ]
        console = Console()
        if ref is None:
            shown = events[:limit]
            if json_out:
                click.echo(json.dumps(shown, indent=2))
                return
            render_history(console, shown)
            return
        run = _find_run(events, ref)
        if run is None:
            raise click.ClickException(f"no cleanup run {ref!r}")
        if json_out:
            click.echo(json.dumps(run, indent=2))
            return
        render_history_run(console, run)
```

with

```python
def _find_run(events: list[dict[str, object]], ref: str) -> dict[str, object] | None:
    if ref.isdigit():
        index = int(ref)
        return events[index - 1] if 1 <= index <= len(events) else None
    return next((e for e in events if e.get("job_id") == ref), None)
```

(`import json` at the top of `cli.py` if not present; `read_audit_events` returns newest first for both backends.)

**Step 3b — renderers in `src/devdoctor/rendering.py`:**

```python
def render_history(console: Console, events: Sequence[Mapping[str, object]]) -> None:
    if not events:
        console.print(Text("no cleanup runs recorded"))
        return
    table = Table(title="cleanup runs (newest first)")
    for name in ("#", "when", "source", "outcome", "ok", "failed", "skipped", "est. reclaimed", "free Δ"):
        table.add_column(name, justify="right" if name in ("#", "ok", "failed", "skipped") else "left")
    for i, e in enumerate(events, 1):
        results = e.get("results") or []
        assert isinstance(results, list)
        ok = sum(r.get("status") == "ok" for r in results)
        failed = sum(r.get("status") == "error" for r in results)
        table.add_row(
            str(i),
            _strip_controls(str(e.get("at", ""))[:19].replace("T", " ")),
            str(e.get("source", "web")),
            str(e.get("outcome", "")),
            f"{ok} ok",
            str(failed),
            str(len(results) - ok - failed),
            f"~{_human_bytes(int(e.get('total_estimated_reclaimed_bytes') or 0))}",
            _free_delta(e),
        )
    console.print(table)


def render_history_run(console: Console, event: Mapping[str, object]) -> None:
    console.print(
        Text(
            f"{str(event.get('at', ''))[:19].replace('T', ' ')} · {event.get('source', 'web')} · "
            f"{event.get('outcome', '')} · ~{_human_bytes(int(event.get('total_estimated_reclaimed_bytes') or 0))} "
            f"estimated reclaimed · free {_free_delta(event)}",
            style="bold",
        )
    )
    plan = event.get("plan") or []
    results = {r.get("entry_id"): r for r in (event.get("results") or [])}
    table = Table(show_lines=False)
    for name in ("#", "provider", "path", "est.", "action", "status", "message"):
        table.add_column(name, overflow="fold" if name in ("path", "message") else "ellipsis")
    for i, p in enumerate(plan, 1):
        r = results.get(p.get("entry_id"), {})
        actions = p.get("actions") or []
        table.add_row(
            str(i),
            _safe_cell(str(p.get("provider", ""))),
            _safe_cell(str(p.get("path") or p.get("label") or "")),
            _estimated_bytes(p.get("estimate_bytes")).lstrip("~"),
            _safe_cell(actions[0] if actions else "(no cleanup action)"),
            str(r.get("status", "")),
            _safe_cell(str(r.get("message") or "")),
        )
    if not plan:
        table.add_row("(no plan recorded)", "", "", "", "", "", "")
    console.print(table)


def _free_delta(event: Mapping[str, object]) -> str:
    before, after = event.get("free_before_bytes"), event.get("free_after_bytes")
    if not isinstance(before, int) or not isinstance(after, int):
        return "—"
    delta = after - before
    return f"{'+' if delta >= 0 else '-'}{_human_bytes(abs(delta))}"
```

`Mapping` comes from `collections.abc`. The `#` column pairs with `history <N>`.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra web pytest tests/test_cli.py -q`
Expected: all pass, including the pre-existing `test_clean_preview_does_not_prompt`.

- [ ] **Step 5: Full Python mirror**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy && uv run --extra dev --extra web pytest -q`
Expected: clean; all passed. If ruff flags `PLR0913` on `clean`, the `# noqa` above covers it; if it flags `PLR0915` on `build_cli`, the function already carries that `noqa`.

- [ ] **Step 6: Commit**

```bash
git add src/devdoctor/cli.py src/devdoctor/rendering.py tests/test_cli.py
git commit -m "feat(cli): show the plan before the confirm, report each entry, record the run

clean prints the itemized plan whatever the flags, streams a line per entry
with the failure reason, ends with estimated vs planned and the real
free-space delta, and appends the run to the shared audit log; --yes skips
only the final confirmation and --risk scopes the run; a new history command
lists past runs (#126).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (`## Commands` block ~line 22–44; `## Safety model` ~line 45)
- Modify: `CHANGELOG.md` (`## [Unreleased]` → `### Added` ~line 60 and `### Changed` ~line 15)
- Modify: `CONTRIBUTING.md` (`## Conventions` ~line 58)

**Interfaces:** consumes the flags and commands from Task 5 exactly as named.

- [ ] **Step 1: README**

In the `## Commands` code block replace the four `devdoctor clean` lines with:

```
devdoctor clean                      # preview: the report table, no prompts, no shell calls
devdoctor clean --execute            # shows the plan, prompts per entry, confirms once, then runs
devdoctor clean --execute --yes-safe # safe entries need no per-entry prompt
devdoctor clean --execute --yes-safe --yes   # unattended: plan still prints, no confirmation
devdoctor clean --execute --risk safe --provider uv-cache   # scope a run
devdoctor history                    # past cleanup runs (CLI and web UI share one log)
devdoctor history 1                  # the newest run, entry by entry
```

After the code block add a short subsection:

```markdown
### What a cleanup run shows

Before anything runs, `clean --execute` prints the plan — every entry with its
path, risk, estimated reclaim and the exact command — and asks once. While it
runs, each entry prints a line as it finishes (`✓` done, `✗` failed with the
command's error, `–` skipped with the reason). The summary states estimated
reclaimed versus planned and the measured free-space change; sizes are
estimates, DevDoctor does not measure freed bytes. Every run is recorded;
`devdoctor history` reads it back. On macOS, freed blocks can stay held by
APFS local snapshots for a while — the summary says so when the measured
change is far below the estimate.
```

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]` → `### Added`, at the top of the list:

```markdown
- **`devdoctor history`** lists past cleanup runs — CLI and web UI now write one
  audit log — and shows a run entry by entry. `clean` gains `--yes` (skip the
  final confirmation only; the plan still prints) and `--risk`. (#126)
```

Under `### Changed`, at the top of the list:

```markdown
- **`devdoctor clean --execute` shows what it will do before it does it.** The
  itemized plan (path, risk, estimated reclaim, exact command) prints before
  the single confirmation whatever the flags; each entry prints a line as it
  finishes, with the command's error when it fails; the summary states
  estimated reclaimed versus planned and the measured free-space change, in
  human units. The scan phase names the running providers. (#126)
```

- [ ] **Step 3: CONTRIBUTING**

Under `## Conventions` add a bullet:

```markdown
- **Presentation observes, never decides.** `cleanup.iter_cleanup_events` is the
  one state machine; the CLI presenter and the web runner only observe its
  events (`on_event`) and answer its prompts. Output code lives in
  `rendering.py`, never in `cleanup.py`.
```

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md CONTRIBUTING.md
git commit -m "docs: describe the cleanup plan, progress, summary and history

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** §2.1/§6 always-plan-always-confirm and `--yes` → Task 5 (plan printed by the observer regardless of `confirm`; `--yes` swaps only the confirm callable). §3.1 observer → Task 2. §3.2 plan on `ConfirmRequired`, same actions as execution → Task 2 (`_build_plan` and `_iter_execute` share `_execution_order`, actions from `entry.cleanup_actions()` as `_run_actions` uses). §3.3 human confirm message → Task 2. §4.1 scan spinner → Task 4 + wiring in Task 5. §4.2 plan table, "Not in this run" → Task 4. §4.3 progress lines, first stderr line → Task 4. §4.4 summary, snapshot hint, exit 2 → Tasks 4/5. §4.5 prompt → Task 4. §5.1 audit builder, keys, web capture via the event, storage backend, logged failure → Tasks 3/5. §5.2 `history` list/detail/`--json`, numbering → Task 5. §6 flags and help, no-TTY abort, `--risk` → Task 5. §7 failure modes: observer raising (Task 2 test), command failing (Task 5 test), audit failure (Task 5 `_record_run`), no TTY (Task 5 test), df unavailable (Task 4 test). §8 tests all present. §10 docs → Task 6.

**Placeholders.** None; each step carries its code. Two figures are read-from-code by the implementer (`Entry` constructor fields, `Risk` serialization) with the file:line to check.

**Type consistency.** `PlannedEntry(entry, actions, estimate_bytes)` + `.lines` (Task 2) is what Tasks 3–5 use; `build_event(results, outcome, *, source, plan, entries, job_id, error, free_before, free_after, now)` (Task 3) matches Task 5's call; `CleanupPresenter.scanning/scan_progress/executing/on_event/prompt_choice/confirm/summary/plan/status_text` (Task 4) match Task 5's wiring and the tests; `render_history`/`render_history_run` (Task 5 Step 3b) match the `history` command; `human_bytes` naming is consistent across Tasks 1–5.
