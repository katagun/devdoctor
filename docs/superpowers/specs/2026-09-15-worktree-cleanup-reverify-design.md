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
  `VerifyRequired(entry)` and receives `Refusal | None` (#114):
  - **`None`:** the entry's actions run exactly as today.
  - **a `Refusal(kind, reason)`:** the entry resolves as
    `CleanResult(entry_id=entry.id, status="skipped", freed_bytes=0,
    message=refusal_message(refusal))`, where the message depends on the kind:
    - `RefusalKind.CHANGED` (the worktree is no longer what the scan offered):
      `changed since the scan: <reason>; rescan before cleaning`;
    - `RefusalKind.UNVERIFIED` (it could not be re-checked):
      `not removed: could not re-check this worktree (<reason>)`.

    No `ExecuteStep` is yielded for it, and it is **not** recorded as removed,
    so approved entries inside its path run normally under the existing §6.4
    rule. `Refusal` and `RefusalKind` live in `devdoctor.types`.
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
| `cleanup.run` (CLI) | `verify: Callable[[Entry], Refusal \| None] \| None = None` | `verify(entry)`, or `Refusal(UNVERIFIED, "no verifier configured")` when `verify` is `None` |
| `cleanup.run_async` | `verify: Callable[[Entry], Refusal \| None] \| None = None` | `await asyncio.to_thread(verify, entry)`, or the same refusal when `None` |
| `web.cleanup_runner.CleanupRunner` | new field `verify: Callable[[Entry], Refusal \| None] \| None = None` | `await asyncio.to_thread(self.verify, entry)`, or the same refusal when `None` |

Wiring:

- `cli.clean` passes `verify=GitWorktreeProvider(shell).verify_removable`.
- `web.routes_clean.start_job` passes
  `verify=GitWorktreeProvider(request.app.state.shell).verify_removable` to
  `CleanupRunner`.

The web job keeps its existing uncontained scan at start (§6.4); verification
covers the time spent waiting on prompts and confirmation. No new SSE event is
added: a refusal reaches the browser as an ordinary result for that entry id.

### 3.3 `GitWorktreeProvider.verify_removable(entry: Entry) -> Refusal | None`

1. **Parse the entry's action.** Exactly one `CommandAction` whose argv is
   `("git", "-C", <repo>, "worktree", "remove", <path>)`, with `<path>` equal to
   `str(entry.path)` and both `<repo>` and `<path>` absolute. Anything else
   returns `UNVERIFIED "unexpected cleanup action"`.
2. **Check git.** `GitRunner.version()`; if it is `None` or below 2.36, return
   `UNVERIFIED "git version unknown"` or `UNVERIFIED "git <x.y.z> is older than
   2.36"`.
3. **Find the record.** `list_worktrees(git, <repo>)`; a failure returns
   `UNVERIFIED "git worktree list failed: <failure summary>"`. The record whose
   realpath equals the entry's path realpath is the worktree. If it is listed
   (not primary or bare) but its directory cannot be read for a reason other
   than not existing, return `UNVERIFIED "cannot access <path>: <reason>"`,
   even when git marks it prunable (git's own stat of the directory failed). If
   there is no such record, or it is the primary worktree, bare, prunable, or
   its directory is missing, return `CHANGED "no longer registered"`.
4. **Recompute repository facts** with the same code the scan uses
   (`_repository_facts`): common dir, default branch, partial-clone check, and,
   when git supports `merge-tree --write-tree`, a merge-tree context in a
   temporary object directory created for this call and removed in a `finally`,
   exactly as in `discover()` (§4.3). It is called with no linked records, so
   `head_commit_times` receives no SHAs and runs no `git log`. Diagnostics the
   provider records during verification are not surfaced; the returned `Refusal`
   (or `None`) is the only output.
5. **Classify** with `_classify(repository, record, registered)`, where
   `registered` is the realpaths of every record in this repository's listing.
   Worktrees registered by other repositories are still caught by the
   nested-repository walk through their `.git` files.
6. **Re-read HEAD after classifying as integrated.** Once `_classify` settles
   on `WorktreeState.INTEGRATED`, re-list the repository (`list_worktrees`
   again) and re-find the worktree by realpath among *every* record, not only
   the linked ones. Refuse with `CHANGED "changed during verification"` if the listing
   fails, the worktree is gone, its HEAD differs from the HEAD read in step 3,
   or it is now locked or prunable. A HEAD move during verification is refused
   outright rather than re-classified against the new HEAD; §2.2's
   re-classification applies only to a HEAD that had already moved before the
   scan, not to one moving during this call.
7. **Answer.** `WorktreeState.INTEGRATED`, once step 6 finds nothing changed,
   returns `None`. `WorktreeState.GIT_ERROR` returns `UNVERIFIED "git error"`;
   every other state returns `CHANGED` with its label text (§5.2), for example
   `not integrated` or `integrated, uncommitted changes`.
8. **Never raise.** Any exception returns `UNVERIFIED str(exc)`.

Verification follows the invocation contract (§4.3): write-free, offline,
`--no-optional-locks`, local variables removed, 30 s per call.

## 4. Error handling

| Failure | Answer | Outcome |
|---|---|---|
| Exception inside `verify_removable` | `UNVERIFIED <exc>` | skipped |
| git missing, unknown version, or below 2.36 | `UNVERIFIED git version unknown` / `git <x.y.z> is older than 2.36` | skipped |
| `worktree list` fails or times out | `UNVERIFIED git worktree list failed: <summary>` | skipped |
| Worktree still listed but its directory cannot be read (even if git marks it prunable) | `UNVERIFIED cannot access <path>: <reason>` | skipped |
| Worktree no longer listed, prunable, primary, bare, or missing | `CHANGED no longer registered` | skipped |
| Any git call during classification fails or times out | `UNVERIFIED git error` (state label) | skipped |
| Worktree gone, locked, prunable, or its HEAD moved between classifying as integrated and the final re-read (§3.3 step 6) | `CHANGED changed during verification` | skipped |
| Temporary object directory cannot be created | falls back to `is-ancestor` (§4.4), which only under-reports integration | skipped unless integration is still proven |
| Adapter given no verifier | `UNVERIFIED no verifier configured` | skipped |
| Web job cancelled while verification runs | the thread finishes; the awaiting coroutine is cancelled, so the removal never starts | existing cancelled-job handling |

## 5. Remaining limitations (spec §11 amendment)

- **Verify-to-remove window.** Verification re-reads HEAD after classifying
  (§3.3 step 6), so the remaining window is from that final read to the start
  of `git worktree remove` — one step and a process spawn. Git offers no lock
  that stops a commit, so this window cannot be closed. An ignored nested
  repository created after the nesting walk passed its directory, or after
  verification, is deleted with the worktree; uncommitted changes made after
  verification are still refused by git.
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
- A `CHANGED` refusal → `skipped`, message
  `changed since the scan: <reason>; rescan before cleaning`, no `ExecuteStep`.
- An `UNVERIFIED` refusal → `skipped`, message
  `not removed: could not re-check this worktree (<reason>)`, no `ExecuteStep`.
- A refused worktree's approved contents execute normally.

### 7.2 Adapters

- `cleanup.run` sends `verify(entry)`; with `verify=None` the worktree is skipped
  with `not removed: could not re-check this worktree (no verifier configured)`
  and no command runs.
- `cleanup.run_async` and `CleanupRunner` run the verifier on a thread other than
  the event loop's, and `CleanupRunner` emits the skipped result in its `done`
  event.
- A web job cancelled while verification is blocked never starts the removal,
  emits no `execute_start`, and reports `cancelled`.
- `cli.clean` and `routes_clean.start_job` pass
  `GitWorktreeProvider(...).verify_removable`.

### 7.3 Provider, on real git (`tests/test_git_worktrees_provider.py`)

Each answer is asserted as a full `Refusal(kind, reason)`.

- Unchanged integrated clean worktree → `None`.
- Commit on a detached HEAD after the scan → `CHANGED not integrated`.
- Commit, or lock, landing during verification → `CHANGED changed during
  verification`, with the commit still present.
- Commit after the scan that is then merged into `origin/main` → `None`.
- Untracked file after the scan → `CHANGED integrated, uncommitted changes`.
- Bare repository created inside the worktree after the scan →
  `CHANGED contains nested repository`.
- Worktree removed and pruned, or deleted but not pruned, after the scan →
  `CHANGED no longer registered`.
- Worktree directory made unreadable after the scan → `UNVERIFIED cannot access
  <path>: Permission denied` (skipped as root).
- A git failure during classification → `UNVERIFIED git error`.
- Entry whose action is not the expected removal → `UNVERIFIED unexpected
  cleanup action`; `_removal_target` rejects relative paths and a mismatched
  path.
- git older than 2.36, an unknown git version, a failing `worktree list`, and an
  internal exception → the matching `UNVERIFIED` reasons.
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
- **Git's own refusal:** a verifier that accepts but dirties the worktree first
  leaves git to refuse the removal (`error` with git's message).

## 8. Rollout

One PR from `main`, containing the implementation, tests, and the documentation
changes in §6. No migration: cleanup actions and snapshot JSON are unchanged.
