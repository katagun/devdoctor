# Re-verify git worktrees immediately before removal — Design

**Issue:** [#110](https://github.com/katagun/devdoctor/issues/110)
**Builds on:** [`2026-09-12-git-worktree-provider-design.md`](2026-09-12-git-worktree-provider-design.md)
(the provider spec, "§" references below point there unless stated otherwise)
**Status:** approved design, 2026-09-15

## 1. Problem

The `git-worktrees` provider classifies worktrees at scan time and offers the
integrated, clean ones as `CommandAction(("git", "-C", <repo>, "worktree",
"remove", <path>))`. Cleanup runs that command as recorded.

`git worktree remove` without `--force` refuses only uncommitted or untracked
changes, a lock, a broken pointer, or a nested repository that is not ignored
(§5.3). It never re-checks integration. So if new work is **committed** in a
worktree between the scan and the removal, the removal succeeds:

- on a branch, the commit survives on the branch ref and only the checkout is
  lost;
- on a **detached HEAD**, which agent tooling uses often, the commit is left
  unreferenced and can be garbage-collected.

The gap is real in both interfaces. The CLI scans, then waits on per-entry
prompts and a final confirmation. The web job re-scans when it starts, then
waits on the same prompts and confirmation.

Reproduced with git 2.50.1 during the PR 4 final review.

## 2. Decisions

1. **Everything is re-checked.** Immediately before a worktree's removal runs,
   the provider re-runs its full classification (§5.1) on that one worktree
   against current state: ownership, default branch, integration of the
   current HEAD, clean status, and the nested-repository walk. Removal proceeds
   only if the worktree is still **integrated, clean**.
2. **A moved HEAD is re-classified, not blocked.** DevDoctor does not compare
   HEAD with the SHA recorded at scan time. If new commits were made and are
   themselves integrated into the current default branch, the worktree is still
   removable; a new unmerged commit fails integration and is refused.
3. **The check is a cleanup event, answered by the provider.** The pure cleanup
   state machine asks; the CLI and web adapters answer by calling the provider.
   The state machine performs no I/O.
4. **Only cleanup re-verifies.** The generated recipe script (`devdoctor
   recipe`) is unchanged: it cannot run Python, and its commands stay commented
   out for review.

## 3. Architecture

### 3.1 Cleanup state machine (`src/devdoctor/cleanup.py`)

- A new event, `VerifyRequired(entry: Entry)`, joins `CleanupEvent`.
- In `_iter_execute`, immediately before `_run_actions(entry)` for an approved
  entry where `is_reclaimable_worktree(entry)` is true, the generator yields
  `VerifyRequired(entry)` and receives `str | None`:
  - **`None`:** the entry's actions run exactly as today.
  - **a reason:** the entry resolves as
    `CleanResult(entry_id=entry.id, status="skipped", freed_bytes=0,
    message=f"changed since the scan: {reason}; rescan before cleaning")`.
    No `ExecuteStep` is yielded for it, and it is **not** recorded as removed,
    so approved entries inside its path run normally under the existing §6.4
    rule.
- Nothing else yields `VerifyRequired`: not declined or skipped selections,
  advice entries, other providers' entries, or preview runs
  (`opts.execute is False`).
- Ordering is unchanged: approved reclaimable worktrees still run first (§6.4).
  Each worktree is verified immediately before its own removal, not in a batch.

### 3.2 Adapters

Every adapter must answer `VerifyRequired`; an unanswered event would stall the
generator loop.

| Adapter | Signature change | Answer |
|---|---|---|
| `cleanup.run` (CLI) | `verify: Callable[[Entry], str \| None] \| None = None` | `verify(entry)`, or `"cannot verify worktree removal"` when `verify` is `None` |
| `cleanup.run_async` | `verify: Callable[[Entry], str \| None] \| None = None` | `await asyncio.to_thread(verify, entry)`, or the same refusal when `None` |
| `web.cleanup_runner.CleanupRunner` | new field `verify: Callable[[Entry], str \| None] \| None = None` | `await asyncio.to_thread(self.verify, entry)`, or the same refusal when `None` |

Wiring:

- `cli.clean` passes `verify=GitWorktreeProvider(shell).verify_removable`.
- `web.routes_clean.start_job` passes
  `verify=GitWorktreeProvider(request.app.state.shell).verify_removable` to
  `CleanupRunner`.

The web job keeps its existing uncontained scan at start (§6.4); verification
covers the time spent waiting on prompts and confirmation. No new SSE event is
added: a refusal reaches the browser as an ordinary result for that entry id.

### 3.3 `GitWorktreeProvider.verify_removable(entry: Entry) -> str | None`

1. **Parse the entry's action.** Exactly one `CommandAction` whose argv is
   `("git", "-C", <repo>, "worktree", "remove", <path>)`, with `<path>` equal to
   `str(entry.path)`. Anything else returns `"could not verify: unexpected
   cleanup action"`.
2. **Check git.** `GitRunner.version()`; if it is `None` or below 2.36, return
   `"cannot verify: git version unknown"` or `"cannot verify: git <x.y.z> is
   older than 2.36"`.
3. **Find the record.** `list_worktrees(git, <repo>)`; a failure returns
   `"git error: <failure summary>"`. The record whose realpath equals the
   entry's path realpath is the worktree; if there is none, or it is the primary
   worktree, bare, prunable, or its directory is missing, return
   `"no longer registered"`.
4. **Recompute repository facts** with the same code the scan uses
   (`_repository_facts`): common dir, default branch, partial-clone check, and,
   when git supports `merge-tree --write-tree`, a merge-tree context in a
   temporary object directory created for this call and removed in a `finally`,
   exactly as in `discover()` (§4.3). It is called with no linked records, so
   `head_commit_times` receives no SHAs and runs no `git log`. Diagnostics the
   provider records during verification are not surfaced; the answer string is
   the only output.
5. **Classify** with `_classify(repository, record, registered)`, where
   `registered` is the realpaths of every record in this repository's listing.
   Worktrees registered by other repositories are still caught by the
   nested-repository walk through their `.git` files.
6. **Answer.** `WorktreeState.INTEGRATED` returns `None`; every other state
   returns its label text (§5.2), for example `not integrated` or
   `integrated, uncommitted changes`.
7. **Never raise.** Any exception returns `f"could not verify: {exc}"`.

Verification follows the invocation contract (§4.3): write-free, offline,
`--no-optional-locks`, local variables removed, 30 s per call.

## 4. Error handling

| Failure | Answer | Outcome |
|---|---|---|
| Exception inside `verify_removable` | `could not verify: <exc>` | skipped |
| git missing, unknown version, or below 2.36 | `cannot verify: …` | skipped |
| `worktree list` fails or times out | `git error: <summary>` | skipped |
| Worktree no longer listed, prunable, primary, bare, or missing | `no longer registered` | skipped |
| Any git call during classification fails or times out | `git error` (state label) | skipped |
| Temporary object directory cannot be created | falls back to `is-ancestor` (§4.4), which only under-reports integration | skipped unless integration is still proven |
| Adapter given no verifier | `cannot verify worktree removal` | skipped |
| Web job cancelled while verification runs | the thread finishes; the awaiting coroutine is cancelled, so the removal never starts | existing cancelled-job handling |

## 5. Remaining limitations (spec §11 amendment)

- **Verify-to-remove window.** The gap between classification and removal
  shrinks from minutes to the time between two subprocesses. A commit landing in
  that instant can still be lost.
- **Recipe script.** `devdoctor recipe` does not re-verify; review it against a
  fresh scan before uncommenting a worktree removal.

## 6. Documentation changes (shipped with the implementation)

- Provider spec §5.3: replace the paragraph added in #111 with: cleanup
  re-classifies each worktree immediately before `git worktree remove`
  (this document), and git then applies its own refusals.
- Provider spec §6.4: add the `VerifyRequired` step to the executor rule.
- Provider spec §11: replace "Commits made between classification and cleanup"
  with the two limitations in §5 above.
- `README.md` "Git worktrees": replace "If you commit in a worktree after
  scanning, rescan before cleaning (#110)." with "Cleanup re-checks each
  worktree immediately before removing it, so one that changed after the scan
  is skipped."
- `CHANGELOG.md` Unreleased → Fixed: an entry for #110.

## 7. Testing

### 7.1 State machine (`tests/test_cleanup_core.py`)

- `VerifyRequired` is yielded only for approved reclaimable `git-worktrees`
  entries, immediately before their `ExecuteStep`; never for declined entries,
  advice entries, other providers, or preview runs.
- `None` → the removal's `ExecuteStep` follows.
- A reason → `skipped`, message
  `changed since the scan: <reason>; rescan before cleaning`, no `ExecuteStep`.
- A refused worktree's approved contents execute normally.

### 7.2 Adapters

- `cleanup.run` sends `verify(entry)`; with `verify=None` the worktree is skipped
  with `cannot verify worktree removal` and no command runs.
- `CleanupRunner` answers through `asyncio.to_thread` and emits the skipped
  result in its `done` event.
- `cli.clean` and `routes_clean.start_job` pass
  `GitWorktreeProvider(...).verify_removable`.

### 7.3 Provider, on real git (`tests/test_git_worktrees_provider.py`)

- Unchanged integrated clean worktree → `None`.
- Commit on a detached HEAD after the scan → `not integrated`.
- Commit after the scan that is then merged into `origin/main` → `None`.
- Untracked file after the scan → `integrated, uncommitted changes`.
- Bare repository created inside the worktree after the scan →
  `contains nested repository`.
- Worktree removed and pruned after the scan → `no longer registered`.
- Entry whose action is not the expected removal → `could not verify:
  unexpected cleanup action`.
- A `RecordingShell` shows every verification call is offline, runs no writing
  command, sets `GIT_OBJECT_DIRECTORY` only on merge-tree, and the temporary
  object directory is gone afterwards; `count-objects` is unchanged.

### 7.4 End to end (`tests/test_worktree_containment_e2e.py`)

- **CLI:** `devdoctor clean --execute` on an integrated, clean, detached
  worktree, where the per-entry prompt callback commits in the worktree before
  answering `y`. The result is `skipped` with
  `changed since the scan: not integrated…`, the worktree still exists, and the
  commit is still an object in the repository (`git cat-file -e <sha>`).
- **Web:** the same scenario through `POST /api/clean/jobs`, committing before
  confirmation; the job's result for the worktree is `skipped` and the commit is
  intact.

## 8. Rollout

One PR from `main`, containing the implementation, tests, and the documentation
changes in §6. No migration: cleanup actions and snapshot JSON are unchanged.
