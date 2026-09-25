# Re-check only the selection before a web cleanup

**Status:** proposed, awaiting review · **Date:** 2026-09-25 ·
**Related:** PR #153 (moved this re-scan off the event loop),
[git worktree provider spec §6.4](2026-09-12-git-worktree-provider-design.md) (why the
cleanup re-scans at all).

## Problem

`POST /api/clean/jobs` re-scans before a job exists, so every selected id is checked
against the disk as it is now (§6.4). It re-runs every provider that owns a selected
id *in full*, although only the selected entries are kept. One `node_modules` folder
therefore re-sizes every `node_modules` on the machine.

Measured on the reference machine (460 GB disk, 267 `node_modules`, 53 worktrees):

| Step of a `node-project-dependencies` re-check | Time |
|---|---|
| Walk the project roots to find the candidates | 10.3 s |
| Size every candidate (41.8 GB) | 43.1 s |
| Size only the selected one (the largest) | 1.5 s |

`git-worktrees` has the same shape: 48.6 s after the walk for 244 entries, most of it
spent classifying and sizing worktrees nobody selected. While a full scan runs
alongside, the same `node_modules` re-check took 222 s. Since PR #153 the wait no
longer freezes the app, but it is still the wait on the review step.

## Non-goals

- Scans for display (`GET /api/scan`, the CLI `scan`) are unchanged: they report
  everything.
- CLI `clean` is unchanged: it scans and acts in one invocation (§6.4).
- Nothing is cached between scans. Candidates are found fresh from disk on every
  cleanup, exactly as today.
- The 10 s project walk stays. Caching it is a separate decision, because it would
  take candidates from memory rather than from disk.
- `large-files`, `docker`, `ollama`, the session-bucket providers and the other
  providers keep full discovery. Either their candidates cost as much to find as to
  measure (`large-files` sizes files during its walk), or they are fast.

## Design

### Provider contract

`Provider` gains one method:

```python
def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
    """The entries ``discover()`` would report now whose (provider-local) id is in ``ids``."""
```

The base implementation is `[] if not ids else [e for e in self.discover() if e.id in ids]`.
It is correct for every provider and no faster. A provider overrides it only when it
can find candidates cheaply and spend its time on each one.

An override splits the provider's work into two phases:

1. **Find candidates.** Run the same enumeration as `discover()`: globs, directory
   listings, the shared project index, `git worktree list`. The same deduplication
   happens here, so the same candidate wins, and each candidate carries the id its
   entry will have.
2. **Build entries.** Do the expensive work (sizing, git classification), for the
   selected candidates only.

`discover()` becomes "phase 1, then phase 2 for all", and `discover_selected(ids)`
becomes "phase 1, filter by id, then phase 2". Both run the same code, so the entries
are identical by construction. A candidate whose entry comes out empty (size 0) is
dropped by the same rule in both.

### Providers that split

| Provider(s) | Phase 1 (always) | Phase 2 (selected only) |
|---|---|---|
| YAML path providers (`PathProvider`) | `resolve_paths()` globs; id `str(path)` | `size_many`, recipe and actions |
| `node-project-dependencies`, `cargo-targets`, `android-project-builds`, `tox-nox-environments` | shared project index; lockfile check picks risk and action; id `str(artifact)` | `size_many` |
| `terraform-workspaces` | as above | `size_many`. The duplicate-plugin note measures every workspace's plugins and is a report diagnostic, so it is skipped under a selection. |
| `git-worktrees` | shared project index; `git worktree list` for **every** repository (removability depends on what every repository registers); id `str(record.path)` | `_repository_facts` only for repositories owning a selected worktree; classification and sizing only for selected worktrees; unverifiable advice entries filtered by id |
| `python-venvs` | the venv walk and its inode dedup; id `str(real)` | `size_many` |
| `xcode-development-data` | directory listings of DerivedData, iOS DeviceSupport and Archives; id `str(path)` | sizing each entry |

### Scan

`discovery.scan` gains `selection: frozenset[str] | None = None`. It holds the
namespaced ids (`"{provider}:{id}"`) a cleanup job selected. When it is set, each
provider is asked for `discover_selected(share)`, where `share` holds the selected
ids that begin with `"{provider.name}:"`, with that prefix removed. A provider whose
share is empty is not called at all. Everything after discovery is
unchanged: reconciliation, `contain=False`, the id check and narrowing to the selection.

Only `routes_clean._scan_selection` passes a selection. An id no provider can
attribute still makes the provider filter `None` (#92), but under a selection every
provider's share is then empty, so that fallback costs nothing. The id is reported
as `unknown_entry` as before.

### Amendment to §6.4

§6.4's second bullet gains a sentence:

> The scan builds only the selected entries: each provider finds its candidates from
> disk as `discover()` would, and measures only those selected (`discover_selected`).

## Safety review

Invariant 3 ("every id a view shows exists when cleanup starts") and invariant 4
("cleanup never acts outside the selection") need candidates found fresh and actions
derived by provider code. Both still hold.

- Candidates are found by the same code, from the disk as it is now. An id the
  provider would not find now is `unknown_entry` (400). A folder that has since become
  empty drops out, as before.
- Risk and actions are derived per candidate by the same code. A `node_modules` that
  lost its lockfile is still dangerous and advice-only. A worktree is still
  classified against every repository's registrations, and still re-verified
  immediately before removal (#110).
- Hard-link reconciliation is per entry (`len(paths) < link_count` inside one entry),
  so building fewer entries does not change any selected entry's shared bytes.
- `covers` and containment only ever look at selected entries (§6.4). No selected
  entry's facts depend on an unselected one, apart from git's registrations, which
  are still read in full.
- What changes is confined to the job's own scan: its per-provider totals and
  diagnostics describe the selection only, and they were never shown.

## Testing

- **Equivalence.** For every overriding provider, over fixture trees:
  `discover_selected(S) == [e for e in discover() if e.id in S]`. S covers empty,
  one entry, all entries, an unknown id, and a mix. This is the test that guards the
  contract.
- **Only the selection is measured.** Spy on `size_many` (and on the git
  classification for worktrees): candidates outside S are never passed in.
- **Empty share.** `discovery.scan(..., selection=S)` never calls `discover()` or
  `discover_selected()` on a provider whose share of S is empty.
- **Route.** `POST /api/clean/jobs` passes its entry ids as the selection. The
  existing 400, 409 and containment tests keep passing unchanged.
- **Measured.** `_scan_selection` on the reference machine, with one `node_modules`
  and one worktree selected: record before and after in the PR.

## Rollout

One PR, stacked on #153 (it changes `_scan_selection`, which #153 introduced), with a
CHANGELOG entry. Expected on the reference machine: `node_modules` about 58 s to
about 12 s, the walk being most of what remains. Cache folders from YAML providers
and Xcode go from a full provider re-size to about the size of the selection.

## Open questions for review

None. The remaining walk (about 10 s) could later be cached for a few minutes, but
that takes candidates from memory and needs its own decision.
