# Git worktree provider — design

- **Status:** Approved design, 2026-09-12. Implementation not started.
- **Issue:** #79
- **Builds on:** #78 (merged in #93), #80 (merged in #94)
- **Related:** #89 (age filtering), #91 (marketing site), #92 (sizing cost), #97 (web display of unmeasured sizes)

## 1. Problem

Agent and git worktrees are the largest category of developer disk use on the
machine this was measured on, and DevDoctor has no model for them.

Measured on one machine (macOS, 460 GB data volume at 97% full) on 2026-09-12.
All git access was read-only; see the appendix for method.

| Measure | Value |
|---|---:|
| Repositories with linked worktrees | 8 |
| Registered linked worktrees | 138 (134 earlier the same day; agents kept creating them) |
| Disk footprint of all worktrees | ~48 GB |
| Bytes other providers already report *inside* worktrees | 27.4 GB (25.1 GB `node_modules`, 2.2 GB `.venv`) |
| **Integrated into the default branch and clean** | **34 worktrees, 10.7 GB** |
| Integrated, but with uncommitted changes | 25 |
| Not integrated | 72 |
| Registered, but the `.git` pointer is broken (repository moved) | 6 |
| Missing or locked | 1 |

Three consequences shape the design:

1. **Size alone is not actionable.** ~48 GB of worktrees exist, but only 10.7 GB
   can be proven safe to remove.
2. **A naive provider double-counts.** 27.4 GB of existing entries sit inside
   worktrees.
3. **Merged is not safe.** 25 integrated worktrees hold uncommitted work; 24 of
   them have modified tracked files, and one has 134.

## 2. Goals

- Report every registered worktree, classified by whether git can prove it
  disposable.
- Offer removal only when git vouches for it: registered, not locked, integrated
  into the default branch, and clean.
- Never count bytes twice.
- Keep scans write-free and offline.

Non-goals are listed in §10.

## 3. Decisions

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Overlap with existing providers | **The worktree owns its bytes when deletable.** Entries inside a deletable worktree are removed from the report. Advice-only worktrees contribute no bytes, and their contents stay individually reclaimable. | *Advice-only, no bytes:* can never offer the reclaim. *Report the remainder only:* an 831 MB worktree would show as 40 MB. *Reuse `shared_bytes`:* that machinery models hardlinks, not containment. |
| Dirty worktrees | **Any modified, staged or untracked file makes the worktree dangerous and advice-only.** | *Report and allow with `--force`:* one wrong classification destroys uncommitted work. *Ignore:* the preview would promise space git refuses to free. |
| Granularity | **One entry per worktree.** | *One per repository:* cleanup becomes all-or-nothing. *Per-repository table, per-worktree JSON:* the two would disagree about what an entry is. |
| Discovery | **Git-first, plus a sweep of worktree folders.** | *Git-only:* misses leftover directories with no `.git`. *Filesystem-first with provider-side containment:* providers run on concurrent threads, so it creates a cross-provider ordering dependency. |
| Where classification is shown | **In `Entry.label`.** | *A new `Entry` field:* touches `Entry`, `Report.to_json`, snapshot loading, the dashboard model and the generated `web/src/api/types.gen.ts`. Snapshot diff compares per-provider totals only, so label text cannot cause diff churn. |
| Integration signal | **`git merge-tree --write-tree`: the result tree equals the default branch's tree.** | *`merge-base --is-ancestor` alone:* misses squash and rebase merges; kept only as a fallback. *Combined-diff `patch-id`:* 0 detections across 78 real candidates, ~70 s to index history, and reports a squash-then-revert as merged. *`git cherry`:* the same revert failure, and misses squash merges. *Remote branch deleted:* two of the three largest repositories keep branches after merge. |

## 4. Architecture

### 4.1 Components

- **`src/devdoctor/providers/git_worktrees.py`** — `GitWorktreeProvider`:
  `name = "git-worktrees"`, `family = "vcs"`, `required_binary = "git"`,
  `platforms = ("darwin", "linux")`, class-level `risk = Risk.RECLAIMABLE`
  (entries set their own risk). Receives the shared `ProjectArtifactIndex`.
- **`src/devdoctor/providers/_git.py`** — git plumbing with no provider
  concerns: argv and environment construction, the per-call timeout,
  `subprocess.TimeoutExpired` handling, and pure parsers for
  `worktree list --porcelain`, `status --porcelain` and `git version`.
- **`src/devdoctor/ports.py`** — `Shell.run` gains
  `env: Mapping[str, str] | None = None`: variables set on top of the inherited
  environment. `RealShell` passes `{**os.environ, **env}` to `subprocess.run`;
  `_NullShell` (`memory/providers.py`) accepts and ignores it; the test
  `FakeShell` records it. The default preserves current behaviour, and no
  existing caller changes.
- **`src/devdoctor/providers/project_artifacts.py`** — the shared index also
  records git candidates (§4.2).
- **`src/devdoctor/types.py`** — `entry_matches_filters()` extracted from
  `Report.filter` (§6.2).
- **`src/devdoctor/discovery.py`** — zero-byte filter exemption, containment
  pass, provider-total recomputation, `scan(..., contain=)` (§6).
- **`src/devdoctor/web/routes_clean.py`** — `contain=False` and selection
  dedupe (§6.4).
- **`src/devdoctor/registry.py`** — registration, in the PR that also ships
  containment (§9).

### 4.2 Discovery

Per scan:

1. **Candidates from the existing walk.** `_index_projects` already visits every
   directory under `_walk.PROJECT_ROOTS`, which include `~/.claude-worktrees`,
   `~/.codex/worktrees` and `~/.cursor/worktrees`. Without walking further it
   records:
   - **repository roots:** directories whose `dirnames` include a `.git`
     directory;
   - **worktree pointers:** directories whose `filenames` include a `.git` file.
     The `gitdir:` line names `<repo>/.git/worktrees/<name>`, from which the
     owning repository is derived, so a repository outside every scan root is
     still reached through a worktree inside one. A pointer to a location that
     does not exist is recorded as broken;
   - **worktree-folder children:** immediate subdirectories of directories named
     `.worktrees`, and of directories named `worktrees` whose parent is
     `.claude`.

   `.git` stays in the prune list. Its presence is observed; it is never
   descended into.
2. **Authoritative enumeration.** One `git worktree list --porcelain` per
   distinct repository. This lists worktrees wherever they are on disk,
   including locations no scan root covers (observed:
   `~/.config/superpowers/worktrees/`).
3. **Per-repository facts, computed once:** the default branch and its tree
   (§4.4); whether the repository is a partial clone (`remote.*.promisor` or
   `extensions.partialClone` set); when merge-tree is in use, the absolute common
   git directory (`rev-parse --path-format=absolute --git-common-dir`); and HEAD
   commit times for all its worktrees from one
   `git log --no-walk=unsorted --format='%H %ct' <sha>…`, chunked at 500 SHAs.
4. **Per-worktree classification** (§5) runs on a pool of 4 worker threads inside
   the provider. This is the first provider with an internal pool; it is
   justified because every check is an independent subprocess.
5. **Unregistered directories.** A worktree-folder child or worktree pointer
   that no repository's porcelain lists becomes the *unverifiable directory*
   advice state (§5.1).

### 4.3 Git invocation contract

Every git call:

- runs as `git --no-optional-locks -C <dir> …` through the `Shell` port, so it
  never refreshes an index or takes a lock;
- sets `GIT_TERMINAL_PROMPT=0` and `GIT_NO_LAZY_FETCH=1`, so it never prompts
  and never fetches missing objects from a promisor remote;
- has a 30 s timeout. `subprocess.TimeoutExpired` — which `RealShell`
  raises — and non-zero exits are caught in `_git.py` and returned as results.
  A git failure never propagates out of `discover()`, where `_discover_one`
  would otherwise discard every worktree entry.

`git merge-tree` additionally sets `GIT_OBJECT_DIRECTORY` to a temporary
directory created for the scan, and `GIT_ALTERNATE_OBJECT_DIRECTORIES` to the
repository's `<common git dir>/objects`. Objects merge-tree writes land in the
temporary directory, which is removed in a `finally` block when `discover()`
returns. Without this, merge-tree persists objects into the user's repository:
2 objects for one conflicting merge in a fixture, and 883 across the eight real
repositories. With it, every repository's `count-objects` total was unchanged.
Only merge-tree gets these variables; the other calls need the real object
store.

The provider never runs `fetch`, `gc`, `prune`, `repair`, or any command that
changes refs or a working tree.

### 4.4 Integration signal

A worktree is **integrated** when merging its HEAD into the default branch would
change nothing:

```
git merge-tree --write-tree <default> <HEAD sha>
# integrated  ⇔  first output line == git rev-parse <default>^{tree}
```

Validated against fixture repositories:

| Scenario | `is-ancestor` | combined `patch-id` | `git cherry` | **merge-tree** |
|---|---|---|---|---|
| Squash merge, 2 commits | no | match | `++` | **integrated** |
| Squash merge with a reviewer edit in the same commit | no | miss | `+` | **integrated** |
| Squash merge after the default branch changed nearby lines | no | miss | `+` | **integrated** |
| Rebase merge, 2 commits | no | miss | `--` | **integrated** |
| Rebase merge, 1 commit | no | match | `-` | **integrated** |
| True merge commit | yes | miss | none | **integrated** |
| Squash merge, then reverted on the default branch | no | match (**wrong**) | `-` (**wrong**) | **not integrated** |
| Not merged | no | miss | `+` | **not integrated** |

On the eight real repositories, merge-tree found 59 integrated worktrees; 7 of
them are invisible to `is-ancestor`.

**Default branch:** `symbolic-ref refs/remotes/origin/HEAD`, then `origin/main`,
then `origin/master`. If none resolves, every worktree in that repository is
advice-only. All eight measured repositories resolved through `origin/HEAD`.

**Staleness errs safe.** The provider never fetches, so the local default-branch
ref may lag the remote. A lagging ref can only make an integrated worktree look
not integrated. The exception is rewritten history on the default branch (force
push); see §11.

**Fallback.** When `git version` is below 2.38 (no `--write-tree`), or the
repository is a partial clone, the signal is `merge-base --is-ancestor <HEAD>
<default>`. The fallback only under-reports integration; it never over-reports
it.

### 4.5 Cost

| Work | Measured or estimated |
|---|---|
| `worktree list --porcelain` | 8 calls |
| `show-toplevel`, `merge-tree`, `status` per worktree | 138 × 3 calls: ~20 s serial, ~5 s on 4 workers (merge-tree median 69 ms, max 792 ms) |
| Sizing | Reclaimable worktrees only: 10.7 GB, ~30 s at the sizer's measured ~0.34 GB/s |

Sizing dominates and is tracked in #92. Advice entries are never sized.

## 5. Classification

### 5.1 States

Registered worktrees are checked in order, and the first match wins.

| # | State | Detected by | Entry |
|---|---|---|---|
| 1 | Primary worktree | first porcelain record | none |
| 2 | Missing, prunable or bare | porcelain `prunable` or `bare`, or the directory is absent | none; one diagnostic per repository suggesting `git -C <repo> worktree prune` |
| 3 | Broken pointer | `rev-parse --show-toplevel` fails, or resolves to a different path | advice |
| 4 | Locked | porcelain `locked [reason]` | advice |
| 5 | Default branch unresolvable | §4.4 | advice |
| 6 | git error | a later call (`merge-tree`, `status`) exits non-zero or times out | advice |
| 7 | Not integrated | §4.4 | advice |
| 8 | Integrated, dirty | `status --porcelain --untracked-files=normal` produces output | advice |
| 9 | Integrated, clean | all checks pass | **reclaimable** |

One further advice state covers directories that are not registered at all (§4.2
step 5): **unverifiable directory**.

Distribution on the measured machine: 34 reclaimable, 25 integrated but dirty,
72 not integrated, 6 broken pointer, 1 missing or locked, 1 unverifiable
directory (`indexcat/.worktrees/feat`).

### 5.2 Entries

Every entry:

- `provider = "git-worktrees"`; `id` and `path` are the worktree path.
- `label = "<repository>/<directory> · <state>"`, where `<repository>` is the
  repository's directory name and `<directory>` is the worktree's directory name.
  When HEAD is on a branch whose name differs from `<directory>`, the branch is
  inserted before the state; when HEAD is detached, `detached @<7-char sha>` is.
  Example: `indexcat/amj · detached @e317178 · broken pointer`. For an
  unverifiable directory, `<repository>` is the directory that contains its
  worktree folder, or, for a `.git` pointer, the repository its `gitdir:` line
  names.
- `mtime` is the HEAD commit's committer time, not the directory mtime, so age
  reflects the last commit (#89). If the batched `git log` for a repository
  fails, `mtime` is `None` for that repository's worktrees and one diagnostic is
  recorded. Unverifiable directories, which have no trustworthy HEAD, use the
  directory's own mtime.

The `<state>` text in labels:

| State | Label text |
|---|---|
| Integrated, clean | `integrated` |
| Integrated, dirty | `integrated, uncommitted changes` |
| Not integrated | `not integrated` |
| Broken pointer | `broken pointer` |
| Locked | `locked` |
| Default branch unresolvable | `no default branch` |
| git error | `git error` |
| Unverifiable directory | `unverifiable` |

**Reclaimable** (state 9):

- `risk = Risk.RECLAIMABLE`
- sized with `size_path_detailed`; `usage = DiskUsage(size, size)`
- `actions = (CommandAction(("git", "-C", <repo>, "worktree", "remove", <path>)),)`
  and `recipe = [<that command, rendered>]`. Never `--force`.

**Advice** (every other state):

- `risk = Risk.DANGEROUS`
- not sized: `size_bytes = 0`, `usage = DiskUsage(None, None)`. The CLI renders
  this as unknown; it counts toward no total, sorts last, and any `--min-size`
  hides it.
- `actions = (AdviceAction(<message>),)`

| State | Advice message |
|---|---|
| Broken pointer | `This worktree's .git file points to <gitdir>, which does not exist; the repository was probably moved. Run "git -C <repo> worktree repair", then rescan.` |
| Locked | `Locked by git: <reason>.`, or `Locked by git.` without a reason |
| Default branch unresolvable | `Cannot determine the default branch of <repo>: no origin/HEAD, origin/main or origin/master.` |
| git error | `git failed while checking this worktree: <first stderr line, or "timed out after 30 s">.` |
| Not integrated | `Not integrated into <default>. Anything inside it that other providers report can still be cleaned individually.` |
| Integrated, dirty | `Integrated into <default>, but has <n> modified and <m> untracked files. Commit, stash or discard them first.` |
| Unverifiable directory | `Inside a worktree folder, but not a registered git worktree. DevDoctor cannot verify what it contains.` |

The broken-pointer command is repository-level on purpose: `git worktree repair`
repairs every broken worktree of that repository in one run.

### 5.3 Classification and `git worktree remove` are independent checks

`git worktree remove` without `--force`, validated against fixtures:

| Worktree state | Result |
|---|---|
| Clean, with gitignored `node_modules/` and `.venv/` | removed; ignored content deleted with it |
| Untracked file | refused |
| Modified tracked file | refused |
| Staged change | refused |
| Nested repository | refused |
| Locked | refused, citing the lock reason |
| Broken `.git` pointer (repository moved) | refused: validation failed |
| Only a stash | removed; the stash survives, because it lives in the repository |

The scan decides what is offered; git re-checks at execution. If a worktree
changes between scan and cleanup, git refuses and cleanup reports git's message
as that entry's error. Deleting uncommitted work requires both checks to be
wrong.

## 6. Containment, filters and cleanup

### 6.1 Zero-byte filter exemption

`_discover_one` drops every entry whose `display_bytes` is 0, to hide empty
caches and cloud-hosted Ollama models. Advice worktree entries are deliberately
unmeasured and would be dropped with them, removing roughly 100 entries from
every report.

The filter keeps an entry when `display_bytes > 0`, **or** its usage is
explicitly unmeasured: `usage is not None and usage.footprint_bytes is None and
usage.reclaimable_bytes is None`. No existing provider emits that shape, so no
existing output changes, and `test_scan_drops_zero_byte_entries` must keep
passing unchanged.

### 6.2 Containment pass

`_reconcile_worktree_containment(entries, filters)` runs in `discovery.scan`
immediately after `_reconcile_shared_usage`, before provider totals are
recomputed. Every consumer of scan results — CLI `scan`, `clean`, `recipe`,
`snapshot` and `diff`, and the web scan, clean, recipe and history routes — goes
through this path.

- An **owner** is an entry with `provider == "git-worktrees"` and
  `risk == Risk.RECLAIMABLE` that satisfies `entry_matches_filters` for the
  scan's filters.
- Every entry from another provider whose `path` equals or lies inside an
  owner's path is removed. Paths are compared after `os.path.realpath`. Entries
  with `path is None` are never contained.
- `entry_matches_filters(entry, *, risks, min_size, providers)` is extracted from
  the inline `keep()` in `Report.filter`, which then calls it. The ownership test
  and real filtering therefore cannot disagree.

### 6.3 Provider totals

`ProviderTiming.bytes` and `ProviderTiming.entries` are computed in
`_discover_one`, before any reconciliation, and `history.diff` sums `bytes`.
The recomputation step therefore recomputes `bytes` and `entries` from the
reconciled entry list, alongside the footprint, reclaimable and shared totals it
already recomputes. Without this, `devdoctor diff` would double-count contained
bytes.

When a worktree becomes integrated, its contents' bytes move from their own
provider's total to `git-worktrees`. Diff reports that as a shift between
providers, not as space freed. Snapshots and the dashboard summary are written
only from unfiltered scans, so persisted totals always follow the same
containment rules.

### 6.4 Cleanup

- `discovery.scan` gains `contain: bool = True`.
- **`POST /api/clean/jobs` scans with `contain=False`.** Its scan establishes
  current state, not what to display, so every id any filtered view could have
  shown still exists, and the existing `unknown_entry` (HTTP 400) check cannot
  fire for a legitimate selection. That scan's totals are never shown.
- After narrowing that report to the selected ids, any selected entry whose path
  lies inside a selected `git-worktrees` entry's path is dropped from the job.
  Removing the worktree deletes it, and keeping it would double-report freed
  bytes.
- **CLI `clean` and `recipe` keep containment on.** They scan and act in one
  invocation, so ids cannot drift, and their `--provider` filter decides
  ownership consistently.

| Scan | Result |
|---|---|
| `devdoctor clean` | an integrated, clean worktree is offered once; its `node_modules` and `.venv` are not offered separately |
| `devdoctor clean --provider node-project-dependencies` | `git-worktrees` entries are filtered out, so nothing is contained: those `node_modules` are offered normally, and no worktree enters scope |
| Web scan with `risk=dangerous` | reclaimable owners fail the filter, so dangerous contents stay visible, and their ids exist in the uncontained cleanup scan |
| Worktree not integrated, or dirty | never an owner; its contents stay individually reclaimable |

### 6.5 Invariants

1. No byte is counted twice in any report or provider total.
2. No entry is hidden from a view unless its owner is visible in that same view.
3. Every id a view shows exists when cleanup starts.
4. Cleanup never acts outside the selection.

## 7. Error handling

| Failure | Behaviour |
|---|---|
| `git` not on `PATH` | provider unavailable, via `required_binary` |
| A per-worktree git call exits non-zero or times out | that worktree takes the matching advice state (§5.1: 3 or 6); the provider continues |
| A repository's `worktree list` fails | one diagnostic for that repository; its worktrees are not reported |
| A repository's batched HEAD-time `git log` fails | `mtime` is `None` for its worktrees; one diagnostic |
| The temporary object directory cannot be created | merge-tree is skipped for the scan, classification falls back to `is-ancestor`, and one diagnostic is recorded |
| The temporary object directory cannot be removed | one diagnostic naming the path |
| Sizing skips unreadable paths | the existing `_note_skipped` diagnostics |

## 8. Testing

**1. Pure unit tests (no subprocess)**

- Porcelain parser: detached HEAD, `locked <reason>`, `prunable`, `bare`, paths
  containing spaces.
- Status parser (modified versus untracked counts), default-branch fallback chain,
  `git version` parsing, label formatting.
- Table-driven classification: one case per §5.1 state, including first-match
  ordering.
- Containment on synthetic entries: owner passes and fails filters, `realpath`
  normalization, `path is None`.
- Provider-total recomputation: `ProviderTiming.bytes` and `.entries` exclude
  contained entries, and `history.diff` does not double-count.
- Zero-byte exemption: `DiskUsage(None, None)` survives; measured-zero entries
  are still dropped.
- `entry_matches_filters` parity: the existing `Report.filter` tests pass
  unchanged.
- Web-cleanup selection dedupe.
- Timeout: a `FakeShell` raising `TimeoutExpired` for one worktree yields advice
  for that worktree while the others classify normally.

**2. Port**

- `RealShell` passes `env` through, checked with a `sh -c 'printf %s "$X"'`
  probe, and preserves the inherited environment.
- `FakeShell` records `env`; existing callers are unaffected.

**3. Real-git integration**

A `GitFixture` helper builds repositories in `tmp_path` under a hermetic
environment: `HOME` (already pinned by `tests/conftest.py`),
`GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, author and committer
identity via environment variables, and `GIT_CEILING_DIRECTORIES=<tmp_path>` so
git never discovers a repository above the fixture.

- Integration scenarios: every row of the §4.4 table.
- States: dirty with a modified file, dirty with an untracked file, locked,
  broken pointer (create worktrees, then move the repository), a `.git`-less
  worktree-folder child, detached HEAD, and a worktree outside every scan root
  that is found through porcelain.
- Rebase fixtures give replayed commits a distinct committer date. Commits
  replayed within the same second are byte-identical to the originals, which
  silently turns a rebase merge into a fast-forward.
- **Write-free:** each repository's `count-objects` total is identical before
  and after `discover()`, and the temporary object directory no longer exists.
- **Offline:** a recording wrapper around `RealShell` confirms every git call set
  `GIT_NO_LAZY_FETCH=1` and `GIT_TERMINAL_PROMPT=0`.
- merge-tree tests skip on git below 2.38. A separate test runs only when `CI`
  is set and fails if git is below 2.38, so the primary path cannot be silently
  skipped in CI.

**4. End-to-end**

- `node_modules` inside an integrated, clean worktree: the report contains only
  the worktree entry, and its footprint counts those bytes once.
- `--provider node-project-dependencies`: those `node_modules` are present, and
  no worktree entry is.
- An advice worktree appears in the report despite having no measured size.
- Web: an id taken from a `risk=dangerous` scan, posted to `/api/clean/jobs`,
  returns 200.
- `devdoctor clean --execute` on an integrated, clean worktree: the directory is
  gone, `git worktree list` no longer lists it, and its gitignored contents are
  gone.
- **Changed between scan and cleanup:** a worktree made dirty after the scan is
  refused by git, and its `CleanResult` is an error carrying git's message.

Tests select entries by provider, path or label, never by list position.

## 9. Rollout

No state of `main` may double-count bytes, so the provider is registered in the
same PR that introduces containment.

| PR | Contents | User-visible |
|---|---|---|
| 1. Foundation | `Shell.run(env=)` in all three implementations; `providers/_git.py` with parsers and the invocation contract; unit and port tests | no |
| 2. Discovery and classification | the index records git candidates; `GitWorktreeProvider` with every §5 state and the write-free, offline contract; real-git integration tests. Not registered | no |
| 3. Containment and registration | zero-byte exemption; `entry_matches_filters`; containment pass and provider-total recomputation; `scan(contain=)`; web cleanup `contain=False` and selection dedupe; registration; end-to-end tests; CHANGELOG | yes |
| 4. Documentation and site | README provider list; then #91 | yes |

Alongside this spec, issues #79 and #91 are corrected to the measured figures in
§1, and #97 covers the web UI rendering an unmeasured footprint as
"0 B" (`web/src/hooks/useScan.ts` maps `footprint_bytes ?? size_bytes`); it
should land no later than PR 3.

## 10. Out of scope for v1

- Running `git worktree repair` or `git worktree prune`; the provider advises
  them only.
- Removing with `--force`, or removing dirty, locked, broken or unverifiable
  worktrees.
- Any network access, including `git fetch` and GitHub API lookups of pull
  request state.
- Sizing advice entries.
- A structured classification field on `Entry` for filtering in the web UI.
- Submodules.

## 11. Known limitations

- **Rewritten default-branch history.** If the default branch was force-pushed
  to drop commits a worktree's branch had contributed, a stale local ref can
  report that worktree as integrated.
- **Unreachable repositories.** A repository outside every scan root, with no
  worktree inside one, is not found.
- **git below 2.38** detects only true merges and fast-forwards.
- **Double sizing.** Contents of a reclaimable worktree are sized by their own
  providers and again as part of the worktree before containment removes them
  (#92).

## Appendix: measurement method

- Repositories: every `.git/worktrees` directory within eight levels of the
  classic code roots (`~/projects`, `~/Documents/projects`, `~/code`, `~/src`,
  `~/dev`, `~/work`, `~/repos`, `~/github`, `~/workspace`). The agent worktree
  homes were not searched as roots; all eight repositories found were under
  `~/projects`, and their porcelain listed worktrees in the agent homes.
- All git commands ran with `--no-optional-locks`. merge-tree ran with
  `GIT_OBJECT_DIRECTORY` pointing at a temporary directory, and each
  repository's object count was checked before and after.
- Dirty state: `git status --porcelain --untracked-files=normal`.
- Worktree sizes: a `du -k` snapshot of the home directory taken at the start of
  the session; sizes for 2 worktrees created afterwards are not included in the
  10.7 GB.
- Fixture results in §4.4 and §5.3 came from throwaway repositories with
  `HOME`, `GIT_CONFIG_NOSYSTEM` and `GIT_CONFIG_GLOBAL` isolated from the user's
  configuration.
