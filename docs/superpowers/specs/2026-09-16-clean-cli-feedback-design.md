# `devdoctor clean` feedback and visibility — Design

**Issue:** [#126](https://github.com/katagun/devdoctor/issues/126)
**Related:** [#127](https://github.com/katagun/devdoctor/issues/127) (uv-cache fails under `uv run`; the
error must be visible), [#117](https://github.com/katagun/devdoctor/issues/117) (scan progress callback),
[#110](https://github.com/katagun/devdoctor/issues/110)/[#114](https://github.com/katagun/devdoctor/issues/114)
(refusal reasons to surface), [#124](https://github.com/katagun/devdoctor/issues/124)/[#125](https://github.com/katagun/devdoctor/issues/125)
(why free space can stay flat)
**Status:** approved design, 2026-09-16

## 1. Problem

A real run on 2026-09-16 of
`devdoctor clean --execute --yes-safe --provider …` showed:

```
⠋ Scanning...                                   (3 minutes, nothing else)
Execute cleanup for 16 entries, estimated reclaimable space
~16839952547 bytes? [y/n] (n): y
                                                (5 minutes, nothing at all)
Estimated reclaimed ~10839035989 bytes; 1 error(s).
```

Before a destructive step the user saw a raw byte count and no list of what
the 16 entries were; with `--yes-safe` the per-entry prompts — the only place
paths were ever shown — are skipped by design. During execution nothing was
printed. Afterwards one entry had failed and the CLI never said which one or
why, although the command's stderr was already captured in
`CleanResult.message`. The CLI writes no audit record; only the web wizard
does. The user reconstructed the list by hand from an earlier `scan --json`.

The core already has everything needed: `cleanup.iter_cleanup_events` yields
`PromptRequired`, `ConfirmRequired(approved, total_bytes, unknown_entries)`,
`VerifyRequired`, `ExecuteStep` and `EntryResolved(result)`; the CLI adapter
`cleanup.run()` answers them through three callbacks and prints nothing.

## 2. Decisions

1. **Always show the plan, always confirm.** Every `--execute` run prints the
   itemized plan before the final confirmation, whatever flags are set. A new
   `--yes` skips only that confirmation; the plan still prints.
2. **A presenter over the event stream.** `run()`/`run_async()` gain an
   `on_event` observer; all CLI output lives in one `CleanupPresenter` in
   `rendering.py`. Selection and execution logic do not change.
3. **The plan travels on `ConfirmRequired`.** The event carries the entries in
   execution order with their rendered actions and estimates, so the presenter
   shows exactly what will run.
4. **Record every run; add `devdoctor history`.** The CLI writes the same audit
   event the web wizard writes, through the same storage backend; a new command
   reads them back.
5. **Human-readable sizes everywhere** in `clean` and `history`; exact bytes
   only in `--json` output and the audit record.
6. **Say what is estimated.** The core measures nothing (`bytes_verified` is
   false); totals are labelled "estimated", and the summary adds the real
   free-space delta of the home volume.

## 3. Core changes (`src/devdoctor/cleanup.py`)

### 3.1 Observer

```python
CleanupObserver = Callable[[CleanupEvent], None]

def run(report, *, shell, prompt_choice, confirm, opts, verify=None,
        on_event: CleanupObserver | None = None) -> list[CleanResult]
async def run_async(report, *, run_line, prompt_choice, confirm, opts, verify=None,
        on_event: CleanupObserver | None = None) -> list[CleanResult]
```

Both adapters call `on_event(event)` for every event the generator yields,
before the adapter answers it. Delivery goes through one helper that catches
every exception, logs it once at warning level with the event class name, and
continues — a presenter can never abort or alter a cleanup (same rule as the
scan progress callback, spec `2026-09-15-scan-progress-stream-design.md` §3).

### 3.2 The plan on `ConfirmRequired`

```python
@dataclass(frozen=True)
class PlannedEntry:
    entry: Entry
    actions: tuple[CleanupAction, ...]   # what _iter_execute will run, in order
    estimate_bytes: int | None           # entry.reclaimable_bytes; None = unknown

@dataclass
class ConfirmRequired:
    approved: list[Entry]
    total_bytes: int
    unknown_entries: int = 0
    plan: tuple[PlannedEntry, ...] = ()  # same entries as `approved`, execution order
```

`iter_cleanup_events` fills `plan` from the approved selections using the same
action list `_run_actions` executes, so plan and execution cannot drift. An
advice-only entry appears with its `AdviceAction`s (rendered as today's recipe
text) and is reported as "advice only; no command executed" when resolved, as
now. The existing web runner ignores `plan` and keeps working unchanged.

### 3.3 Confirm message

`_confirm_summary` is replaced by a one-line human-readable message,
`"Execute these 16 entries (~15.7G estimated, +2 unknown)?"`, built with the
same byte formatter the report table uses. The itemized table is the
presenter's job (§4.2), not the message's.

### 3.4 Results

`CleanResult` is unchanged. Its `message` already carries the command's stderr
(or stdout, or `exit N`) on failure, the refusal reason on a skipped worktree,
and "advice only; no command executed" for advice entries; the presenter and
the audit record surface it.

## 4. The CLI presenter (`src/devdoctor/rendering.py`)

`CleanupPresenter(console: Console)` exposes `on_event`, `prompt_choice`,
`confirm`, `scan_progress` and `summary(results, outcome, delta)`. `clean` in
`cli.py` only wires it up. All output is written through Rich with control
characters stripped by the existing `_strip_controls`, paths shown with `~`
for the home directory, sizes via `_human_bytes` / `_human_bytes_or_unknown`.

### 4.1 Scan phase

The spinner text is updated from `discovery.scan(on_progress=)` events:
`scanning… 12/22 providers · running: docker, xcode-development-data` (at most
three names, then `+N`), then `scanning… reconciling` after the last
`ProviderFinished`. Same wording as the web progress line.

### 4.2 Plan (on `ConfirmRequired`)

Printed always, including under `--yes-safe` and `--yes`:

```
Cleanup plan — 16 entries, ~15.7G estimated (+2 unknown)
  #  provider              risk     est.   path                              action
  1  uv-cache              safe     5.6G   ~/.cache/uv                       uv cache clean
  2  lm-studio-extensions  safe     2.8G   ~/.cache/lm-studio/extensions     rm -rf …
 …
Not in this run: 3 dangerous (pass --allow-dangerous), 2 declined, 1 provider skipped
Execute these 16 entries (~15.7G estimated, +2 unknown)? [y/N]
```

Rows are in execution order; the `action` column shows the first rendered
action and `(+N more)` when an entry has several; `est.` shows `unknown` for
`None`; the risk column uses the report table's colours. The "Not in this run"
line is derived from the `EntryResolved` events with status `skipped` that
arrived before the confirm (selection-phase skips).

### 4.3 Progress (on `ExecuteStep` / `EntryResolved`)

One line per entry when it resolves, numbered over the plan:

```
[ 1/16] ✓ uv-cache              ~/.cache/uv                    ~5.6G
[ 5/16] ✗ docker-installer      ~/Library/…/com.docker.install failed: rm: …: Operation not permitted
[ 9/16] – git-worktrees         indexcat/pr-327                skipped: changed since the scan: …; rescan before cleaning
[12/16] · docker-vm-disk        ~/Library/Containers/…/vms     advice only; no command executed
```

Failure and skip text is `CleanResult.message`, first line only, truncated
to the console width; the full text is in the audit record. While a command
runs, the spinner shows `[ 5/16] running: rm -rf …`.

### 4.4 Summary

```
Done: 14 ok · 1 failed · 1 skipped — ~10.8G estimated reclaimed of ~15.7G planned
free space 71.2G → 78.0G (+6.8G) · recorded: devdoctor history
```

When the measured delta is below half the estimated reclaim, one more line:
`APFS local snapshots can hold freed blocks; see docs "why did my free space
not change"`. Exit code 2 when any entry failed, as today.

### 4.5 Per-entry prompt

Today's `prompt_choice` (header line, recipe hint, `[y]es / [n]o / [a]ll-in-provider
/ [s]kip-provider / [q]uit`) moves into the presenter unchanged except that
sizes are already human-readable there.

## 5. Audit record and `devdoctor history`

### 5.1 One event builder

`src/devdoctor/cleanup_audit.py`:

```python
def build_event(results, outcome, *, source: Literal["cli", "web"], plan: Sequence[PlannedEntry],
                job_id: str | None = None, error: str | None = None,
                free_before: int | None = None, free_after: int | None = None) -> dict[str, Any]
```

The web runner's `_write_audit` and the CLI both call it; the web runner takes
the plan from the `ConfirmRequired` event it observes through `on_event` (the
same observer the CLI uses), so both sources record identical plan rows. The
event keeps every
key readers rely on today — `type: "cleanup"`, `job_id`, `outcome`,
`total_freed_bytes` (compatibility), `total_estimated_reclaimed_bytes`,
`bytes_verified`, `results[{entry_id, status, freed_bytes, message, bytes_verified}]`,
`error` — and adds:

- `source`: `"cli"` or `"web"`; `job_id` is `null` for CLI runs.
- `at`: ISO-8601 UTC set by the builder (storage backends that already stamp
  `at` keep theirs).
- `plan`: `[{entry_id, provider, label, path, risk, estimate_bytes, actions: [rendered lines]}]`.
- per result: `provider`, `label`, `path`, so a record reads on its own.
- `free_before_bytes`, `free_after_bytes`: `shutil.disk_usage(Path.home()).free`
  measured before the confirm and after the last entry; `null` when unavailable.

The CLI writes through `build_storage(load_app_settings())`, the same backend
the web app uses (filesystem `audit.jsonl` or SQLite), so runs from either
side show in both. A write failure is logged with traceback and never changes
the exit code.

### 5.2 `devdoctor history`

```
devdoctor history [--limit N] [--json]        # runs, newest first
devdoctor history <N | job_id> [--json]       # one run's entries
```

List view: `when · source · outcome · ok/failed/skipped · ~est. reclaimed ·
free +Δ`, numbered from 1 = newest; `history <N>` takes that number and
`history <job_id>` a web run's id. Detail view: the plan rows with each entry's status and message.
Reads `storage.read_audit_events`, the call the web History page makes;
snapshot events stay web-only. `--json` prints the raw events.

## 6. Flags

| Flag | Meaning |
|---|---|
| `--execute` | unchanged: without it, `clean` prints the report table and "Preview only" |
| `--yes-safe` | unchanged: auto-approve safe entries; others still prompt per entry |
| `--yes` | new: skip the final confirmation only; the plan still prints; with `--yes-safe` a run is fully unattended |
| `--allow-dangerous` | unchanged |
| `--provider` | unchanged |
| `--risk safe,reclaimable` | new: same parser as `scan --risk`; scopes the run like `--provider` |

Every option gets help text. Without a TTY and without `--yes`, the
confirmation reads no answer and the run aborts with
`no terminal to confirm on; pass --yes to run unattended`.

## 7. Failure modes

| Case | Behaviour |
|---|---|
| Presenter raises | logged once per event, cleanup continues, results unchanged |
| Command fails | `✗` line with the first stderr line; full text in the audit; exit 2 |
| Confirm declined or `q` | plan already printed; results recorded as skipped; audit `outcome: "aborted"` |
| Audit write fails | warning with traceback; exit code unaffected |
| No TTY, no `--yes` | aborts before executing, message above |
| `df` unavailable | delta line omitted; audit fields `null` |
| Advice-only entry | shown in the plan with its text; resolved as today |

## 8. Testing

Every test is written before the code it covers and watched fail.

- `tests/test_cleanup.py`: `run()` and `run_async()` deliver every event to
  `on_event` in order; a raising observer leaves results identical; `plan` on
  `ConfirmRequired` lists approved entries in execution order with rendered
  actions and estimates, including an advice-only entry and an unknown estimate;
  `plan` matches `approved` one to one.
- `tests/test_cleanup_audit.py`: `build_event` shape for ok/error/skipped
  results; CLI and web events share the key set; `free_*` null when not given;
  `at` is UTC ISO-8601.
- `tests/test_rendering.py`: presenter output captured through
  `Console(record=True, width=120)` — plan table with human sizes, `~` paths and
  the exact command; `unknown` estimate; the "Not in this run" line; a failed
  entry's progress line carries the stderr; the summary shows estimated vs
  planned and the delta; the snapshot hint appears only when the delta is
  below half the estimate; control characters stripped.
- `tests/test_cli.py`: `clean --execute --yes-safe --yes` with a `FakeShell`
  whose one command fails prints the plan, the progress lines, the failure
  reason and exits 2; the audit event lands in the test data dir with
  `source: "cli"`; `history` lists the run and `history 1` shows the entries;
  `--risk` scoping; no TTY without `--yes` aborts with the message.
- `tests/web/test_routes_clean.py`: the wizard's audit event keeps its
  previous keys and gains `source: "web"`.

## 9. Out of scope

- Measuring freed bytes per entry (`bytes_verified` stays false).
- `--json` for `clean` itself.
- Showing the plan table in the web wizard (it has its own review step).
- The uv-under-uv failure itself (#127); this spec makes it visible.

## 10. Documentation

README: `clean` walkthrough with the new output, `history`, the flags table;
CHANGELOG "Changed" and "Added" entries; CONTRIBUTING: presenters observe
events and never live in the core.
