# Time Machine local snapshots provider + covering entries — Design

**Issue:** [#124](https://github.com/katagun/devdoctor/issues/124)
**Related:** [#123](https://github.com/katagun/devdoctor/issues/123) (same session),
[#125](https://github.com/katagun/devdoctor/issues/125) (why free space can stay flat),
[#126](https://github.com/katagun/devdoctor/issues/126) (clean CLI feedback)
**Status:** approved design, 2026-09-19 (both modes; bundle covers the newest snapshot)

## 1. Problem

A real run on 2026-09-16: after a Docker image prune freed 25 GB inside
`Docker.raw`, `df` did not move at all — 15 hourly Time Machine **local
snapshots** (`com.apple.TimeMachine.*.local`) were holding the blocks.
`tmutil thinlocalsnapshots / 50000000000 4` released **56 GB** in one go
(14 GB → 70 GB free, 97% → 84%). Nothing DevDoctor scans today shows this,
and it dwarfed every other bucket.

Probing this Mac: `tmutil listlocalsnapshots /` lists 24 hourly
`com.apple.TimeMachine.<date>.local` entries plus three
`com.apple.os.update-*` snapshots that must never be touched. No command
exposes per-snapshot size (`diskutil apfs listSnapshots` only marks them
purgeable; this OS prints no purgeable figure in `diskutil info`). So the
entries are honestly unmeasured, like advice-only worktrees: the scan shows
the count and age span instead of bytes.

## 2. Decisions

1. **New provider `time-machine-local-snapshots`**, family `system` (already
   used), darwin only, `required_binary = "tmutil"`, risk `reclaimable`.
   Local snapshots are restore points until the next backup; deleting them
   does not touch the external backup. The entry text says so plainly.
2. **Both modes (A and C), user picks at the prompt.** The provider emits one
   **bundle** entry (mode A: everything except the newest snapshot) plus one
   entry **per snapshot, including the newest** (mode C).
3. **A generic `covers` relation in the core.** `Entry` gains
   `covers: tuple[str, ...] = ()`, the ids of entries it supersedes. The
   bundle covers every per-snapshot id, including the newest — approving the
   bundle always keeps one restore point; deleting everything means declining
   it and picking snapshots individually. The rule lives in the cleanup core
   so the CLI and the web runner share it, and future aggregate/per-item
   pairs (Docker category rows vs per-volume rows, per-toolchain views) can
   reuse the same field.
4. **No double execution, ever.** Covered entries are never prompted and never
   executed while their coverer is approved; the bundle's 23 delete commands
   run newest-first, so if the oldest snapshot expires mid-run only the last
   command fails.
5. **Surfaces show everything; the recipe de-duplicates.** The scan table and
   web scan list show all ~25 rows (unsized, so they sort last and never push
   real numbers down). `build_script` omits entries whose coverer is present,
   with a comment saying so. `scan --json` and the web entry types gain
   `covers`. Greying out covered checkboxes in the wizard is an explicit
   follow-up — the core rule already guarantees correctness.

## 3. Provider (`src/devdoctor/providers/time_machine.py`)

```python
class TimeMachineSnapshotsProvider(Provider):
    name = "time-machine-local-snapshots"
    family = "system"
    description = "Time Machine local snapshots"
    platforms = ("darwin",)
    risk = Risk.RECLAIMABLE
    required_binary = "tmutil"
```

- **Discover:** run `tmutil listlocalsnapshots /` (`check=False`). Parse
  `com.apple.TimeMachine.<YYYY-MM-DD-HHMMSS>.local` lines; drop everything
  else, in particular `com.apple.os.update-*`. Non-zero exit or empty result
  yields no entries plus a provider diagnostic (the existing
  `diagnostics` drain into `Report.diagnostics`).
- **Bundle entry:** id `"all-but-newest"`, label
  `Time Machine local snapshots, all but the newest (N)`, one
  `CommandAction(("tmutil", "deletelocalsnapshots", ts))` per older snapshot,
  **newest-first**, all listed in the plan before the confirm. `mtime` is the
  oldest snapshot's epoch so the Stale column and a future `--older-than`
  work. `covers` is every per-snapshot id, newest included.
- **Per-snapshot entries:** id `f"snapshot-{ts}"`, label
  `Time Machine local snapshot <YYYY-MM-DD HH:MM:SS>`, one delete command
  each, `mtime` from the parsed timestamp. The newest snapshot gets an entry
  too — it is only deletable by declining the bundle and picking it.
- **Sizing:** `size_bytes=0`, `usage=DiskUsage(None, None)` (unmeasured:
  `display_bytes` 0, kept by `discovery.scan`, sorted last). No sudo was
  needed on macOS 26.
- **Registry:** one line in `_CLASS_PROVIDERS` (`registry.py`).

## 4. Core changes (`src/devdoctor/cleanup.py`, `src/devdoctor/types.py`)

### 4.1 `Entry.covers`

```python
@dataclass(frozen=True)
class Entry:
    ...
    # Ids of entries this entry supersedes. Empty for all existing providers.
    covers: tuple[str, ...] = ()
```

`Report.to_json` serialises it as `"covers": list(e.covers)`; `from_json`
reads `tuple(e.get("covers") or [])` so snapshots written before this change
keep loading. The web scan payload flows through `to_json`, so the frontend
entry type gains optional `covers` with no other web contract change.

### 4.2 Selection rule

`SelectionState` gains `"skipped:covered"`. `_iter_selection` stable-partitions
candidates so a covering entry is prompted **before** the entries it covers
(scan order today puts the unmeasured bundle last, so without this the rule
could not work), then applies, per covered entry:

| Coverer state | Covered entries |
|---|---|
| `approved` (`y`, or `a` = mode A) | `skipped:covered`, no prompt, reason `covered by <bundle label>` |
| `skipped:user` (`n`) | prompted individually (mode C) |
| `skipped:provider-skip` (`s`), `skipped:quit`, `skipped:dangerous` | inherit the same state, no prompt |

The covers check runs **before** the `provider_override` check in
`_auto_state`: pressing `a` at the bundle prompt must resolve the snapshots
as covered, not auto-approve each of them. `_apply_choice` is unchanged.

The coverer label for the skip reason is found by reverse lookup (the
approved selection whose `covers` contains the entry id);
`_to_result` maps a bare `"covered"` to a generic fallback. Plan, history and
audit handling is unchanged: the bundle is the only approved entry, covered
snapshots appear under "Not in this run" as `covered by …`, and the web
runner — which drives `iter_cleanup_events` directly after filtering to the
ticked ids — inherits the rule: ticking both bundle and snapshots resolves
the snapshots as skipped-covered with no second command ever running on a
vanished snapshot.

`_execution_order`, `VerifyRequired` and the observer contract are untouched.

### 4.3 Recipe

`build_script` already comments every destructive line out; double-listing
would only be noise. When a provider's entries include a covering entry,
covered entries emit their label line with
`(covered by <bundle label>; commands listed above)` and no command lines.

## 5. Failure modes

| Case | Behaviour |
|---|---|
| `tmutil` missing / non-darwin | provider unavailable, nothing emitted |
| `tmutil` fails or no snapshots | no entries + diagnostic in `Report.diagnostics` |
| Snapshot expires mid-run | only its delete command fails; newest-first order bounds this to the last command |
| Old snapshot JSON without `covers` | loads with `covers == ()`, rule never fires |
| Coverer approved, snapshot ticked in web | resolves `skipped` with `covered by …`; never executed |

## 6. Testing

Every test is written before the code it covers and watched fail.

- `tests/test_time_machine_provider.py`: parse fixture with
  `com.apple.os.update-*` lines mixed in (filtered); empty output and
  non-zero exit (no entries + diagnostic); newest snapshot excluded from the
  bundle's actions but present as an entry; newest-first action order; bundle
  `covers` every snapshot id including the newest; bundle `mtime` is the
  oldest; unavailable off darwin. `FakeShell` keyed on argv, following the
  docker/ollama tests.
- `tests/test_cleanup.py`: coverer prompted before covered entries despite
  scan order; approving the bundle skips covered entries with no
  `PromptRequired` and reason `covered by …`; declining prompts each
  snapshot; `a` at the bundle is mode A (bundle approved, all covered);
  `s`/`q` inherit without prompts; a covered entry is never executed even
  when approved-looking input exists for it; `covers` survives a
  `to_json`/`from_json` round trip and defaults to `()` on old payloads.
- `tests/web/test_cleanup_runner.py` (or `test_routes_clean.py`): selecting
  bundle plus snapshots resolves the snapshots as skipped-covered.
- Recipe test: `build_script` lists the bundle's commands once and the
  covered snapshots as label-only lines.

## 7. Out of scope

- Per-snapshot byte sizes (the OS does not expose them).
- Thinning by an amount (option B: no UI surface asks for an amount today).
- Greying out covered checkboxes in the web wizard (follow-up; correctness
  does not need it).
- Changing `--yes-safe` semantics (reclaimable entries always prompt).

## 8. Documentation

README: provider-list entry plus a line in the "why free space did not
change" explanation pointing at this provider; CHANGELOG "Added" entry.
