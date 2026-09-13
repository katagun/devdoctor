# Git Worktree Provider, PR 3: Containment and Registration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `git-worktrees` provider on without double-counting: contain the contents of removable worktrees, keep every cleanup selection valid, show unmeasured entries honestly in the web UI, and register the provider.

**Architecture:** A shared `entry_matches_filters` predicate and a new `devdoctor.containment` module decide which entries a reclaimable worktree hides. `discovery.scan` applies containment after hard-link reconciliation and recomputes provider totals, with `contain=False` for the web cleanup scan, which instead drops selected entries inside a selected worktree. Scans are persisted only when unfiltered (#103). The web table carries `null` footprints through to a "not measured" cell (#97). Deferred PR 2 review findings are fixed before `registry.py` registers the provider, and end-to-end tests exercise scan, CLI and web against real git.

**Tech Stack:** Python 3.12, pytest, real git, FastAPI/httpx, Click; React, TypeScript, Vitest, Bun; ruff, mypy (strict), eslint, uv.

**Spec:** `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` — this plan implements §9 PR 3, using §6 (containment, filters and cleanup), §8 layers 1 and 4, and the §5, §7 and §11 amendments from PR 2 review; plus issues #97 and #103. Built on PR 1 (#100), the #98 hardening (#101) and PR 2 (#108), base `724450d`.

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100`, rules `E, F, I, UP, B, SIM, PL, RUF`; `mypy --strict` over `src/devdoctor`. Web: `tsc --noEmit`, eslint, vitest, all run by CI.
- The zero-byte filter keeps an entry when `display_bytes > 0`, **or** its usage is explicitly unmeasured: `usage is not None and usage.footprint_bytes is None and usage.reclaimable_bytes is None`; `test_scan_drops_zero_byte_entries` must keep passing unchanged. (spec §6.1)
- Containment (`contain_worktree_contents`) runs in `discovery.scan` immediately after `_reconcile_shared_usage`, before provider totals are recomputed. Every consumer of scan results goes through this path. (spec §6.2)
- An **owner** is an entry with `provider == "git-worktrees"` and `risk == Risk.RECLAIMABLE` that satisfies `entry_matches_filters` for the scan's filters. Every entry from another provider whose `path` equals or lies inside an owner's path is removed. Paths are compared after `os.path.realpath`. Entries with `path is None` are never contained. (spec §6.2)
- `entry_matches_filters(entry, *, risks, min_size, providers)` is extracted from the inline `keep()` in `Report.filter`, which then calls it. (spec §6.2)
- Provider totals: `ProviderTiming.bytes` and `ProviderTiming.entries` are recomputed from the reconciled entry list, alongside the footprint, reclaimable and shared totals. (spec §6.3)
- `discovery.scan` gains `contain: bool = True`. `POST /api/clean/jobs` scans with `contain=False`; after narrowing that report to the selected ids, any selected entry whose path lies inside a selected `git-worktrees` entry's path is dropped from the job. CLI `clean` and `recipe` keep containment on. (spec §6.4)
- Invariants: no byte is counted twice in any report or provider total; no entry is hidden from a view unless its owner is visible in that same view; every id a view shows exists when cleanup starts; cleanup never acts outside the selection. (spec §6.5)
- Snapshots and the dashboard summary are written only from unfiltered scans. (spec §6.3; #103)
- Web: carry `null` footprints through `CacheTableRow` instead of substituting `size_bytes`, render them as not measured, sort unmeasured rows after measured ones, and never count them as hidden under the minimum-size filter. (#97)
- The provider is registered in this PR, together with containment, and the CHANGELOG ships here. (spec §9)
- Tests select entries by provider, path or label, never by list position. (spec §8)
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. PR descriptions end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

## Commands

Run everything from the repository root. These mirror CI (`.github/workflows/ci.yml`):

```bash
uv run --extra dev --extra web ruff check src tests
uv run --extra dev --extra web ruff format --check src tests
uv run --extra dev --extra web mypy
uv run --extra dev --extra web pytest
cd web && bun ci && bun run lint && bun run typecheck && bunx vitest run && bun run build
```

`bun run build` rewrites the tracked placeholder `src/devdoctor/web/_static/dist/index.html`; restore it with `git checkout -- src/devdoctor/web/_static/dist/index.html` before committing.

## Decisions where the spec is silent

1. **Containment lives in `src/devdoctor/containment.py`** with two public functions: `contain_worktree_contents` for views and `drop_contents_of_selected_worktrees` for cleanup selections. `discovery.py` and `routes_clean.py` stay thin.
2. **Cleanup dedupe owners are selected reclaimable worktrees only.** Removing an advice-only worktree runs nothing, so its selected contents stay in the job.
3. **`ScanFilters.is_unfiltered`** is the single predicate for the discovery filter step, the dashboard summary and auto-snapshots, so #103 cannot regress through one of the three drifting.
4. **#97 keeps `CacheTableRow.size_bytes` numeric** (`0` for unmeasured rows) so every existing sum still works; `footprint_bytes === null` marks an unmeasured row, and only a *missing* field falls back to `size_bytes`. The minimum-size split moves into `web/src/lib/scanRows.ts` so it can be unit-tested, and the cleanup review shows "not measured". The dashboard treemap already skips rows with no bytes and is unchanged.
5. **Provider hardening** (PR 2 review, deferred to this PR):
   - `WorktreeFacts.toplevel_ok` becomes `ownership_ok`, which is what it has meant since PR 2's ownership check.
   - `advice_message(DIRTY)` raises without status counts instead of printing "0 modified and 0 untracked".
   - Diagnostics: an unknown git version says so (`could not determine the git version`); an old one names it (`needs git 2.36, found git 2.35.8`); the prune suggestion says worktrees are `missing or no longer valid`, since a porcelain `prunable` record can still have a directory.
   - `worktree_belongs_to` reads the admin `gitdir` file only if it is a regular file: a FIFO there would block a worker thread forever.
   - New tests: symlinked `.git` and folder children are not candidates; an unregistered broken pointer is unverifiable; a bare repository's worktree classifies without diagnostics; an unborn worktree is a git error; a repository reached by both the walk and a pointer is listed once.
   - Spec: §5.1 row 3 names `<common git dir>/worktrees/<name>` exactly; row 6 includes `merge-base --is-ancestor`; §7 covers an undeterminable git version; §11 documents newline paths and relative pointers under symlinked roots.
6. **`registry.load_providers` passes the shared index by `issubclass(cls, (NodeModulesProvider, GitWorktreeProvider))`**, which selects the same four project-artifact providers as before (all subclass `NodeModulesProvider`) plus the worktree provider, and lets mypy see the `index` parameter.
7. **Left as they are:** a valueless `extensions.partialClone` key and unreadable config (both only choose the conservative `is-ancestor` fallback), and an empty lock reason rendering as `Locked by git.` (the spec's wording).

## Verified behaviour

Observed while this plan's code was built against git 2.50.1:

- `git worktree remove` on a worktree that gained an untracked file after the scan exits non-zero with `fatal: '<path>' contains modified or untracked files, use --force to delete it`; `cleanup.run` turns that into a `CleanResult` with `status="error"` and that message.
- `devdoctor clean --execute` under `click.testing.CliRunner` reads the per-entry prompt and the final confirmation from `input="y\ny\n"`.
- A `node_modules` next to a `package.json` without a lockfile is `dangerous`; inside an integrated, clean worktree it is contained in the full view but visible, and cleanable, from `risk=dangerous`.
- `git worktree add --orphan` (git 2.42+) creates a worktree whose porcelain HEAD is unborn; classification reports it as a git error.

## File Structure

| File | Task | Change | Responsibility |
|---|---|---|---|
| `src/devdoctor/types.py` | 1 | modify | Filter primitives |
| `tests/test_types.py` | 1 | modify | test |
| `src/devdoctor/containment.py` | 2 | create | Containment module |
| `tests/test_containment.py` | 2 | create | test |
| `src/devdoctor/discovery.py` | 3 | modify | Scan pipeline: unmeasured entries, containment and provider totals |
| `tests/test_discovery.py` | 3 | modify | test |
| `src/devdoctor/web/routes_scan.py` | 4 | modify | Web routes: uncontained cleanup scan, selection dedupe, unfiltered-only snapshots |
| `src/devdoctor/web/routes_clean.py` | 4 | modify | Web routes: uncontained cleanup scan, selection dedupe, unfiltered-only snapshots |
| `tests/web/test_routes_scan.py` | 4 | modify | test |
| `tests/web/test_routes_clean.py` | 4 | modify | test |
| `src/devdoctor/providers/_worktree_states.py` | 5 | modify | Provider hardening before registration |
| `src/devdoctor/providers/_git_queries.py` | 5 | modify | Provider hardening before registration |
| `src/devdoctor/providers/git_worktrees.py` | 5 | modify | Provider hardening before registration |
| `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` | 5 | modify | Provider hardening before registration |
| `tests/test_worktree_states.py` | 5 | modify | test |
| `tests/test_git_queries.py` | 5 | modify | test |
| `tests/test_git_worktrees_provider.py` | 5 | modify | test |
| `tests/test_project_index_git_candidates.py` | 5 | modify | test |
| `web/src/hooks/useScan.ts` | 6 | modify | Web UI: unmeasured entries are not 0 B (#97) |
| `web/src/components/CacheTable.tsx` | 6 | modify | Web UI: unmeasured entries are not 0 B (#97) |
| `web/src/lib/scanRows.ts` | 6 | create | Web UI: unmeasured entries are not 0 B (#97) |
| `web/src/pages/Scan.tsx` | 6 | modify | Web UI: unmeasured entries are not 0 B (#97) |
| `web/src/components/CleanupWizard/ReviewStep.tsx` | 6 | modify | Web UI: unmeasured entries are not 0 B (#97) |
| `web/tests/unit/useScan.test.tsx` | 6 | modify | test |
| `web/tests/unit/CacheTable.test.tsx` | 6 | modify | test |
| `web/tests/unit/scanRows.test.ts` | 6 | create | test |
| `src/devdoctor/registry.py` | 7 | modify | Registration, end-to-end tests and CHANGELOG |
| `CHANGELOG.md` | 7 | modify | Registration, end-to-end tests and CHANGELOG |
| `tests/test_registry.py` | 7 | modify | test |
| `tests/test_worktree_containment_e2e.py` | 7 | create | test |

---

### Task 1: Filter primitives

One predicate decides whether an entry passes a scan's filters, so the entries a view shows and the worktrees allowed to hide their contents can never disagree (spec §6.2).

**Files:**
- Modify: `src/devdoctor/types.py`
- Test (modify): `tests/test_types.py`

**Interfaces:**
- Consumes: `Entry.display_bytes`, `DiskUsage`, `Report.filter` (existing, `src/devdoctor/types.py`).
- Produces:
  - `devdoctor.types.entry_matches_filters(entry: Entry, *, risks: set[Risk] | frozenset[Risk] | None = None, min_size: int = 0, providers: set[str] | frozenset[str] | None = None) -> bool`; `Report.filter` calls it.
  - `Entry.is_unmeasured -> bool` (property): `usage is not None and usage.footprint_bytes is None and usage.reclaimable_bytes is None`.
  - `ScanFilters.is_unfiltered -> bool` (property): `min_size_bytes == 0 and risks is None and providers is None`.

- [ ] **Step 1: Write the failing tests**

Apply this change to `tests/test_types.py` (for example with `git apply`):

```diff
diff --git a/tests/test_types.py b/tests/test_types.py
--- a/tests/test_types.py
+++ b/tests/test_types.py
@@ -2,12 +2,15 @@ import json
 from datetime import UTC, datetime
 from pathlib import Path

+import pytest
+
 from devdoctor.types import (
     SNAPSHOT_SCHEMA_VERSION,
     CleanResult,
     CleanupOpts,
     DiffReport,
     DiffRow,
+    DiskUsage,
     Entry,
     ProviderTiming,
     Report,
@@ -15,6 +18,7 @@ from devdoctor.types import (
     ScanFilters,
     ShellResult,
     SnapshotKind,
+    entry_matches_filters,
 )


@@ -411,3 +415,63 @@ def test_filter_preserves_kind_and_timings() -> None:
     assert filtered.started_at == started
     assert filtered.duration_ms == 777
     assert filtered.per_provider == r.per_provider
+
+
+def _filter_entry(provider: str, risk: Risk, size: int, usage=None) -> Entry:
+    return Entry(provider, "id", Path("/x"), "x", size, None, risk, [], usage=usage)
+
+
+@pytest.mark.parametrize(
+    ("entry", "kwargs", "expected"),
+    [
+        pytest.param(_filter_entry("a", Risk.SAFE, 10), {}, True, id="no-filters"),
+        pytest.param(
+            _filter_entry("a", Risk.SAFE, 10), {"risks": {Risk.DANGEROUS}}, False, id="risk"
+        ),
+        pytest.param(_filter_entry("a", Risk.SAFE, 10), {"providers": {"b"}}, False, id="provider"),
+        pytest.param(
+            _filter_entry("a", Risk.SAFE, 10), {"min_size": 11}, False, id="below-min-size"
+        ),
+        pytest.param(_filter_entry("a", Risk.SAFE, 10), {"min_size": 10}, True, id="at-min-size"),
+        pytest.param(
+            _filter_entry("a", Risk.DANGEROUS, 0, usage=DiskUsage(None, None)),
+            {"min_size": 1},
+            False,
+            id="unmeasured-hidden-by-any-min-size",
+        ),
+        pytest.param(
+            _filter_entry("a", Risk.DANGEROUS, 0, usage=DiskUsage(None, None)),
+            {},
+            True,
+            id="unmeasured-shown-without-min-size",
+        ),
+    ],
+)
+def test_entry_matches_filters(entry, kwargs, expected):
+    assert entry_matches_filters(entry, **kwargs) is expected
+
+
+@pytest.mark.parametrize(
+    ("usage", "expected"),
+    [
+        pytest.param(DiskUsage(None, None), True, id="unmeasured"),
+        pytest.param(DiskUsage(0, 0), False, id="measured-zero"),
+        pytest.param(DiskUsage(None, 5), False, id="reclaimable-known"),
+        pytest.param(None, False, id="legacy-size-only"),
+    ],
+)
+def test_entry_is_unmeasured(usage, expected):
+    assert _filter_entry("a", Risk.SAFE, 0, usage=usage).is_unmeasured is expected
+
+
+@pytest.mark.parametrize(
+    ("filters", "expected"),
+    [
+        pytest.param(ScanFilters(), True, id="defaults"),
+        pytest.param(ScanFilters(min_size_bytes=1), False, id="min-size"),
+        pytest.param(ScanFilters(risks=frozenset({Risk.SAFE})), False, id="risks"),
+        pytest.param(ScanFilters(providers=frozenset({"a"})), False, id="providers"),
+    ],
+)
+def test_scan_filters_is_unfiltered(filters, expected):
+    assert filters.is_unfiltered is expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_types.py -q`
Expected: collection error, `ImportError: cannot import name 'entry_matches_filters' from 'devdoctor.types'`.

- [ ] **Step 3: Implement**

Apply this change to `src/devdoctor/types.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/types.py b/src/devdoctor/types.py
--- a/src/devdoctor/types.py
+++ b/src/devdoctor/types.py
@@ -189,6 +189,15 @@ class Entry:
     def footprint_bytes(self) -> int | None:
         return self.usage.footprint_bytes if self.usage is not None else self.size_bytes

+    @property
+    def is_unmeasured(self) -> bool:
+        """The provider deliberately did not size this entry: ``DiskUsage(None, None)``."""
+        return (
+            self.usage is not None
+            and self.usage.footprint_bytes is None
+            and self.usage.reclaimable_bytes is None
+        )
+
     @property
     def reclaimable_bytes(self) -> int | None:
         return self.usage.reclaimable_bytes if self.usage is not None else self.size_bytes
@@ -299,6 +308,30 @@ class ScanFilters:
     risks: frozenset[Risk] | None = None
     providers: frozenset[str] | None = None

+    @property
+    def is_unfiltered(self) -> bool:
+        """Whether the scan shows everything: only such scans may be stored or summarised."""
+        return self.min_size_bytes == 0 and self.risks is None and self.providers is None
+
+
+def entry_matches_filters(
+    entry: Entry,
+    *,
+    risks: set[Risk] | frozenset[Risk] | None = None,
+    min_size: int = 0,
+    providers: set[str] | frozenset[str] | None = None,
+) -> bool:
+    """Whether ``entry`` passes a scan's filters.
+
+    ``Report.filter`` and worktree containment both use this, so the entries a view
+    shows and the worktrees that may hide their contents can never disagree.
+    """
+    if risks is not None and entry.risk not in risks:
+        return False
+    if providers is not None and entry.provider not in providers:
+        return False
+    return entry.display_bytes >= min_size
+

 @dataclass(frozen=True)
 class CleanupOpts:
@@ -401,15 +434,12 @@ class Report:
         min_size: int = 0,
         providers: set[str] | frozenset[str] | None = None,
     ) -> Report:
-        def keep(e: Entry) -> bool:
-            if risks is not None and e.risk not in risks:
-                return False
-            if providers is not None and e.provider not in providers:
-                return False
-            return e.display_bytes >= min_size
-
         return Report(
-            entries=[e for e in self.entries if keep(e)],
+            entries=[
+                e
+                for e in self.entries
+                if entry_matches_filters(e, risks=risks, min_size=min_size, providers=providers)
+            ],
             scanned_at=self.scanned_at,
             hostname=self.hostname,
             platform=self.platform,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_types.py -q`
Expected: no failures.

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_types.py src/devdoctor/types.py
git commit -m "feat(scan): share scan filter predicates and mark unmeasured entries" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Containment module

A small module owns the path rules, independent of discovery and the web layer.

**Files:**
- Create: `src/devdoctor/containment.py`
- Test (create): `tests/test_containment.py`

**Interfaces:**
- Consumes: `entry_matches_filters`, `ScanFilters`, `Risk`, `Entry` (Task 1).
- Produces (`src/devdoctor/containment.py`):
  - `WORKTREE_PROVIDER = "git-worktrees"`
  - `contain_worktree_contents(entries: list[Entry], filters: ScanFilters) -> list[Entry]` (spec §6.2)
  - `drop_contents_of_selected_worktrees(selected: list[Entry]) -> list[Entry]` (spec §6.4)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_containment.py`:

```python
from pathlib import Path

import pytest

from devdoctor.containment import (
    contain_worktree_contents,
    drop_contents_of_selected_worktrees,
)
from devdoctor.types import DiskUsage, Entry, Risk, ScanFilters

ALL = ScanFilters()


def _entry(provider: str, path: Path | None, *, risk=Risk.RECLAIMABLE, size=100) -> Entry:
    usage = DiskUsage(None, None) if size == 0 else DiskUsage(size, size)
    return Entry(
        provider=provider,
        id=f"{provider}:{path}",
        path=path,
        label=str(path),
        size_bytes=size,
        mtime=None,
        risk=risk,
        recipe=[],
        usage=usage,
    )


def _worktree(path: Path, *, risk=Risk.RECLAIMABLE) -> Entry:
    return _entry("git-worktrees", path, risk=risk, size=0 if risk is Risk.DANGEROUS else 500)


def _ids(entries):
    return [e.id for e in entries]


WT = Path("/p/app/.worktrees/feature")


def test_contents_of_a_reclaimable_worktree_are_removed():
    owner = _worktree(WT)
    inside = _entry("node-project-dependencies", WT / "node_modules")
    same_path = _entry("tox-nox-environments", WT)
    outside = _entry("node-project-dependencies", Path("/p/app/node_modules"))
    result = contain_worktree_contents([owner, inside, same_path, outside], ALL)
    assert _ids(result) == [owner.id, outside.id]


def test_a_sibling_sharing_the_name_prefix_is_not_contained():
    owner = _worktree(WT)
    sibling = _entry("node-project-dependencies", Path("/p/app/.worktrees/feature-2/node_modules"))
    assert _ids(contain_worktree_contents([owner, sibling], ALL)) == [owner.id, sibling.id]


def test_advice_worktrees_contain_nothing():
    owner = _worktree(WT, risk=Risk.DANGEROUS)
    inside = _entry("node-project-dependencies", WT / "node_modules")
    assert _ids(contain_worktree_contents([owner, inside], ALL)) == [owner.id, inside.id]


@pytest.mark.parametrize(
    "filters",
    [
        pytest.param(ScanFilters(risks=frozenset({Risk.DANGEROUS})), id="risk-filter"),
        pytest.param(ScanFilters(min_size_bytes=10_000), id="min-size"),
        pytest.param(
            ScanFilters(providers=frozenset({"node-project-dependencies"})), id="provider"
        ),
    ],
)
def test_an_owner_outside_the_view_contains_nothing(filters):
    owner = _worktree(WT)
    inside = _entry("node-project-dependencies", WT / "node_modules", risk=Risk.DANGEROUS)
    assert _ids(contain_worktree_contents([owner, inside], filters)) == [owner.id, inside.id]


def test_entries_without_a_path_are_never_contained():
    owner = _worktree(WT)
    logical = _entry("docker", None)
    assert _ids(contain_worktree_contents([owner, logical], ALL)) == [owner.id, logical.id]


def test_worktree_entries_are_never_contained_by_another_worktree():
    outer = _worktree(Path("/p/app"))
    nested = _worktree(Path("/p/app/.worktrees/feature"))
    assert _ids(contain_worktree_contents([outer, nested], ALL)) == [outer.id, nested.id]


def test_paths_are_compared_after_resolving_symlinks(tmp_path):
    real = tmp_path / "real" / "feature"
    (real / "node_modules").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    owner = _worktree(link / "feature")
    inside = _entry("node-project-dependencies", real / "node_modules")
    assert _ids(contain_worktree_contents([owner, inside], ALL)) == [owner.id]


def test_cleanup_selection_drops_contents_of_selected_reclaimable_worktrees():
    owner = _worktree(WT)
    inside = _entry("node-project-dependencies", WT / "node_modules")
    elsewhere = _entry("node-project-dependencies", Path("/p/other/node_modules"))
    result = drop_contents_of_selected_worktrees([inside, owner, elsewhere])
    assert _ids(result) == [owner.id, elsewhere.id]


def test_cleanup_selection_keeps_contents_of_a_selected_advice_worktree():
    owner = _worktree(WT, risk=Risk.DANGEROUS)
    inside = _entry("node-project-dependencies", WT / "node_modules")
    assert _ids(drop_contents_of_selected_worktrees([owner, inside])) == [owner.id, inside.id]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_containment.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'devdoctor.containment'`.

- [ ] **Step 3: Implement**

Create `src/devdoctor/containment.py`:

```python
"""Git worktree containment: count bytes inside a removable worktree once.

A reclaimable git worktree's removal deletes everything inside it, including
``node_modules``, virtualenvs and build output that other providers report on
their own. Without containment those bytes would be counted twice and offered
for cleanup twice.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §6
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from devdoctor.types import Entry, Risk, ScanFilters, entry_matches_filters

WORKTREE_PROVIDER = "git-worktrees"


def contain_worktree_contents(entries: list[Entry], filters: ScanFilters) -> list[Entry]:
    """Remove entries that lie inside a reclaimable worktree the view shows (spec §6.2).

    An owner is a reclaimable ``git-worktrees`` entry that passes ``filters``. An entry
    hidden because of an owner therefore always has that owner visible in the same
    view, and an owner filtered out of the view hides nothing.
    """
    owners = [
        entry
        for entry in entries
        if _is_owner(entry)
        and entry_matches_filters(
            entry,
            risks=filters.risks,
            min_size=filters.min_size_bytes,
            providers=filters.providers,
        )
    ]
    return _without_contents(entries, owners)


def drop_contents_of_selected_worktrees(selected: list[Entry]) -> list[Entry]:
    """Drop selected entries that removing a selected reclaimable worktree deletes (§6.4).

    Keeping them would run a cleanup for content the worktree removal already
    deletes, and report its bytes as freed twice.
    """
    return _without_contents(selected, [entry for entry in selected if _is_owner(entry)])


def _is_owner(entry: Entry) -> bool:
    return (
        entry.provider == WORKTREE_PROVIDER
        and entry.risk is Risk.RECLAIMABLE
        and entry.path is not None
    )


def _without_contents(entries: list[Entry], owners: Iterable[Entry]) -> list[Entry]:
    roots = {os.path.realpath(owner.path) for owner in owners if owner.path is not None}
    if not roots:
        return list(entries)
    return [
        entry
        for entry in entries
        if entry.provider == WORKTREE_PROVIDER
        or entry.path is None
        or not _inside_any(os.path.realpath(entry.path), roots)
    ]


def _inside_any(path: str, roots: set[str]) -> bool:
    """Whether ``path`` equals or lies inside one of ``roots`` (all realpaths)."""
    current = path
    while True:
        if current in roots:
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_containment.py -q`
Expected: `11 passed`.

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_containment.py src/devdoctor/containment.py
git commit -m "feat(scan): contain entries inside reclaimable git worktrees" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Scan pipeline: unmeasured entries, containment and provider totals

`discovery.scan` keeps deliberately unmeasured entries, removes contents of reclaimable worktrees the view shows, and recomputes provider totals afterwards so `devdoctor diff` never double-counts (spec §6.1–§6.4).

**Files:**
- Modify: `src/devdoctor/discovery.py`
- Test (modify): `tests/test_discovery.py`

**Interfaces:**
- Consumes: `Entry.is_unmeasured`, `ScanFilters.is_unfiltered` (Task 1); `contain_worktree_contents` (Task 2).
- Produces: `discovery.scan(providers, filters, now, *, contain: bool = True) -> Report`, with provider totals (`bytes`, `entries`, `footprint_bytes`, `reclaimable_bytes`, `shared_bytes`) recomputed from the final entry list.

- [ ] **Step 1: Write the failing tests**

Apply this change to `tests/test_discovery.py` (for example with `git apply`):

```diff
diff --git a/tests/test_discovery.py b/tests/test_discovery.py
--- a/tests/test_discovery.py
+++ b/tests/test_discovery.py
@@ -1,10 +1,11 @@
+import dataclasses
 from datetime import UTC, datetime
 from pathlib import Path

 from devdoctor import discovery
 from devdoctor.discovery import scan
 from devdoctor.providers.base import Provider
-from devdoctor.types import Entry, Risk, ScanFilters, SnapshotKind
+from devdoctor.types import DiskUsage, Entry, Risk, ScanFilters, SnapshotKind
 from tests.conftest import FakeShell


@@ -319,3 +320,80 @@ def test_scan_shares_shell_safely_across_concurrent_providers() -> None:
     report = discovery.scan(providers, ScanFilters(), datetime.now(UTC))
     assert {e.provider for e in report.entries} == {f"s{i}" for i in range(12)}
     assert len(report.per_provider) == 12
+
+
+def test_scan_keeps_unmeasured_entries_but_drops_measured_zero() -> None:
+    unmeasured = dataclasses.replace(
+        _fe(provider="git-worktrees", size=0), id="advice", usage=DiskUsage(None, None)
+    )
+    measured_zero = dataclasses.replace(
+        _fe(provider="git-worktrees", size=0), id="empty", usage=DiskUsage(0, 0)
+    )
+    p = _FakeProvider(name="git-worktrees", entries=[unmeasured, measured_zero])
+    report = discovery.scan([p], ScanFilters(), datetime.now(UTC))
+    assert [e.id for e in report.entries] == ["git-worktrees:advice"]
+    [timing] = report.per_provider
+    assert (timing.entries, timing.bytes) == (1, 0)
+
+
+def test_scan_min_size_hides_unmeasured_entries() -> None:
+    unmeasured = dataclasses.replace(_fe(size=0), usage=DiskUsage(None, None))
+    p = _FakeProvider(entries=[unmeasured, _fe(size=500)])
+    report = discovery.scan([p], ScanFilters(min_size_bytes=1), datetime.now(UTC))
+    assert [e.size_bytes for e in report.entries] == [500]
+
+
+def _at(provider: str, path: str, size: int, risk: Risk = Risk.RECLAIMABLE) -> Entry:
+    return dataclasses.replace(
+        _fe(provider=provider, size=size),
+        id=path,
+        path=Path(path),
+        label=path,
+        risk=risk,
+        usage=DiskUsage(size, size),
+    )
+
+
+def _worktree_scan(filters: ScanFilters | None = None, **kwargs):
+    worktrees = _FakeProvider(
+        name="git-worktrees", entries=[_at("git-worktrees", "/p/wt/feature", 1_000)]
+    )
+    node = _FakeProvider(
+        name="node-project-dependencies",
+        entries=[
+            _at("node-project-dependencies", "/p/wt/feature/node_modules", 600),
+            _at("node-project-dependencies", "/p/app/node_modules", 300),
+            _at("node-project-dependencies", "/p/wt/feature/web/node_modules", 50, Risk.DANGEROUS),
+        ],
+    )
+    return discovery.scan([worktrees, node], filters or ScanFilters(), datetime.now(UTC), **kwargs)
+
+
+def test_scan_contains_entries_inside_a_reclaimable_worktree() -> None:
+    report = _worktree_scan()
+    assert sorted(str(e.path) for e in report.entries) == ["/p/app/node_modules", "/p/wt/feature"]
+    timings = {pt.name: pt for pt in report.per_provider}
+    assert (
+        timings["node-project-dependencies"].bytes,
+        timings["node-project-dependencies"].entries,
+    ) == (300, 1)
+    assert timings["node-project-dependencies"].footprint_bytes == 300
+    assert (timings["git-worktrees"].bytes, timings["git-worktrees"].entries) == (1_000, 1)
+    assert sum(pt.bytes for pt in report.per_provider) == report.total_bytes() == 1_300
+
+
+def test_scan_without_containment_keeps_every_entry() -> None:
+    report = _worktree_scan(contain=False)
+    assert len(report.entries) == 4
+    timings = {pt.name: pt for pt in report.per_provider}
+    assert timings["node-project-dependencies"].entries == 3
+
+
+def test_scan_keeps_contents_when_the_filters_hide_the_worktree() -> None:
+    report = _worktree_scan(ScanFilters(risks=frozenset({Risk.DANGEROUS})))
+    assert [str(e.path) for e in report.entries] == ["/p/wt/feature/web/node_modules"]
+
+
+def test_scan_with_a_provider_filter_excluding_worktrees_contains_nothing() -> None:
+    report = _worktree_scan(ScanFilters(providers=frozenset({"node-project-dependencies"})))
+    assert len(report.entries) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_discovery.py tests/test_history.py -q`
Expected: three of the six new tests fail: `test_scan_keeps_unmeasured_entries_but_drops_measured_zero` and `test_scan_contains_entries_inside_a_reclaimable_worktree` with `AssertionError`, and `test_scan_without_containment_keeps_every_entry` with `TypeError: scan() got an unexpected keyword argument 'contain'`. The other three already hold and guard against containing too much.

- [ ] **Step 3: Implement**

Apply this change to `src/devdoctor/discovery.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/discovery.py b/src/devdoctor/discovery.py
--- a/src/devdoctor/discovery.py
+++ b/src/devdoctor/discovery.py
@@ -9,6 +9,7 @@ from concurrent.futures import ThreadPoolExecutor
 from dataclasses import dataclass
 from datetime import UTC, datetime

+from devdoctor.containment import contain_worktree_contents
 from devdoctor.providers.base import Provider
 from devdoctor.types import (
     DiskUsage,
@@ -131,8 +132,10 @@ def _discover_one(p: Provider) -> _ProviderResult:
         # "nothing to reclaim" — most commonly cloud-hosted ollama models
         # (`ollama list` reports `-` for size, which parses to 0), but also
         # empty cache directories. Surfacing them is noise that the user
-        # can't act on.
-        provider_entries = [e for e in p.discover() if e.display_bytes > 0]
+        # can't act on. Entries a provider deliberately left unmeasured
+        # (`DiskUsage(None, None)`, such as advice-only git worktrees) are kept:
+        # their size is unknown, not zero.
+        provider_entries = [e for e in p.discover() if e.display_bytes > 0 or e.is_unmeasured]
     except Exception as exc:  # isolate one provider's failure from the scan
         dt_ms = int((time.monotonic() - t0) * 1000)
         msg = f"{p.name}: discovery failed: {exc}"
@@ -167,6 +170,8 @@ def scan(
     providers: list[Provider],
     filters: ScanFilters,
     now: datetime,
+    *,
+    contain: bool = True,
 ) -> Report:
     """Run every available provider, collect entries, apply filters, sort.

@@ -182,6 +187,11 @@ def scan(
     timings are immune to NTP adjustments mid-scan. The returned Report
     has kind=MANUAL by default; the API layer overrides to AUTO when it's
     about to write an auto-snapshot.
+
+    With ``contain`` (the default), entries inside a reclaimable git worktree that
+    the filtered view shows are removed, so their bytes count once, under
+    ``git-worktrees``. The web cleanup scan passes ``contain=False``: it
+    establishes current state for a selection, not what to display (spec §6.4).
     """
     started_at = datetime.now(UTC)
     # Freeze the set (and order) of available providers up front; availability
@@ -210,22 +220,9 @@ def scan(
             per_provider.append(result.timing)

     entries = _reconcile_shared_usage(entries)
-    timing_by_name = {timing.name: timing for timing in per_provider}
-    per_provider = [
-        dataclasses.replace(
-            timing,
-            footprint_bytes=unique_footprint_bytes(
-                [entry for entry in entries if entry.provider == timing.name]
-            ),
-            reclaimable_bytes=estimated_reclaimable_bytes(
-                [entry for entry in entries if entry.provider == timing.name]
-            ),
-            shared_bytes=unique_shared_bytes(
-                [entry for entry in entries if entry.provider == timing.name]
-            ),
-        )
-        for timing in (timing_by_name[name] for name in timing_by_name)
-    ]
+    if contain:
+        entries = contain_worktree_contents(entries, filters)
+    per_provider = _recompute_provider_totals(per_provider, entries)

     scanned_at = datetime.now(UTC)
     duration_ms = int((scanned_at - started_at).total_seconds() * 1000)
@@ -247,7 +244,7 @@ def scan(
         diagnostics=diagnostics,
     )

-    if filters.min_size_bytes or filters.risks is not None or filters.providers is not None:
+    if not filters.is_unfiltered:
         report = report.filter(
             risks=filters.risks,
             min_size=filters.min_size_bytes,
@@ -257,6 +254,34 @@ def scan(
     return report


+def _recompute_provider_totals(
+    per_provider: list[ProviderTiming], entries: list[Entry]
+) -> list[ProviderTiming]:
+    """Recompute every provider total from the reconciled, contained entry list.
+
+    ``bytes`` and ``entries`` were first computed in ``_discover_one``, before
+    containment; ``history.diff`` sums ``bytes``, so leaving them would count
+    contained bytes twice (spec §6.3).
+    """
+    by_provider: dict[str, list[Entry]] = {}
+    for entry in entries:
+        by_provider.setdefault(entry.provider, []).append(entry)
+    totals: list[ProviderTiming] = []
+    for timing in per_provider:
+        own = by_provider.get(timing.name, [])
+        totals.append(
+            dataclasses.replace(
+                timing,
+                bytes=sum(entry.size_bytes for entry in own),
+                entries=len(own),
+                footprint_bytes=unique_footprint_bytes(own),
+                reclaimable_bytes=estimated_reclaimable_bytes(own),
+                shared_bytes=unique_shared_bytes(own),
+            )
+        )
+    return totals
+
+
 def _platform() -> str:
     if sys.platform.startswith("linux"):
         return "linux"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_discovery.py tests/test_history.py -q`
Expected: no failures.

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_discovery.py src/devdoctor/discovery.py
git commit -m "feat(scan): keep unmeasured entries, contain worktree contents, recompute totals" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Web routes: uncontained cleanup scan, selection dedupe, unfiltered-only snapshots

The cleanup scan must see every id any filtered view could have shown (spec §6.4), and only unfiltered scans may be persisted (#103, which spec §6.3 relies on).

**Files:**
- Modify: `src/devdoctor/web/routes_scan.py`
- Modify: `src/devdoctor/web/routes_clean.py`
- Test (modify): `tests/web/test_routes_scan.py`
- Test (modify): `tests/web/test_routes_clean.py`

**Interfaces:**
- Consumes: `ScanFilters.is_unfiltered` (Task 1); `drop_contents_of_selected_worktrees` (Task 2); `discovery.scan(..., contain=)` (Task 3); `CleanupRunner.report` and `RunnerRegistry.active()` (existing).
- Produces: `GET /api/scan` stores the dashboard summary and auto-snapshots only for unfiltered scans; `POST /api/clean/jobs` scans with `contain=False` and drops selected entries inside a selected reclaimable worktree.

- [ ] **Step 1: Write the failing tests**

Apply this change to `tests/web/test_routes_scan.py` (for example with `git apply`):

```diff
diff --git a/tests/web/test_routes_scan.py b/tests/web/test_routes_scan.py
--- a/tests/web/test_routes_scan.py
+++ b/tests/web/test_routes_scan.py
@@ -170,3 +170,22 @@ def test_scan_with_snapshot_flag_prunes_to_retention(tmp_path, monkeypatch) -> N
     remaining = sorted(p.name for p in snapshot_dir.glob("*--auto.json"))
     # 5 seeded + 1 new = 6; prune(keep=3) leaves 3.
     assert len(remaining) == 3
+
+
+def test_filtered_scans_never_write_an_auto_snapshot(tmp_path, monkeypatch) -> None:
+    """A filtered report covers part of the disk; storing it reads as a drop (#103)."""
+    from devdoctor import history
+
+    client = _client(tmp_path, monkeypatch)
+    snapshot_dir = history.default_snapshot_dir()
+    for query in ("risk=safe", "min_size=100M", "provider=ollama"):
+        resp = client.get(
+            f"/api/scan?snapshot=true&snapshot_min_interval_ms=0&{query}",
+            headers={"Host": "testserver"},
+        )
+        assert resp.status_code == 200
+    assert not snapshot_dir.exists() or list(snapshot_dir.glob("*.json")) == []
+
+    resp = client.get("/api/scan?snapshot=true", headers={"Host": "testserver"})
+    assert resp.status_code == 200
+    assert len(list(snapshot_dir.glob("*--auto.json"))) == 1
```

Apply this change to `tests/web/test_routes_clean.py` (for example with `git apply`):

```diff
diff --git a/tests/web/test_routes_clean.py b/tests/web/test_routes_clean.py
--- a/tests/web/test_routes_clean.py
+++ b/tests/web/test_routes_clean.py
@@ -184,3 +184,81 @@ async def test_unknown_entry_id_is_400(tmp_path, monkeypatch):
         )
         assert r.status_code == 400
         assert r.json()["error"]["code"] == "unknown_entry"
+
+
+@pytest.mark.asyncio
+async def test_cleanup_scan_is_uncontained_and_drops_contents_of_selected_worktrees(
+    tmp_path, monkeypatch
+):
+    from devdoctor.types import (
+        CommandAction,
+        DeletePathAction,
+        DiskUsage,
+        Entry,
+        Report,
+        Risk,
+    )
+    from devdoctor.web import routes_clean
+
+    worktree_path = tmp_path / "wt" / "feature"
+
+    def entry(provider, id_, path, risk, action):
+        return Entry(
+            provider=provider,
+            id=id_,
+            path=path,
+            label=str(path),
+            size_bytes=100,
+            mtime=None,
+            risk=risk,
+            recipe=[],
+            usage=DiskUsage(100, 100),
+            actions=(action,),
+        )
+
+    worktree = entry(
+        "git-worktrees",
+        "git-worktrees:feature",
+        worktree_path,
+        Risk.RECLAIMABLE,
+        CommandAction(
+            ("git", "-C", str(tmp_path / "app"), "worktree", "remove", str(worktree_path))
+        ),
+    )
+    inside = entry(
+        "node-project-dependencies",
+        "node:inside",
+        worktree_path / "node_modules",
+        Risk.DANGEROUS,
+        DeletePathAction(worktree_path / "node_modules"),
+    )
+    outside = entry(
+        "node-project-dependencies",
+        "node:outside",
+        tmp_path / "app" / "node_modules",
+        Risk.RECLAIMABLE,
+        DeletePathAction(tmp_path / "app" / "node_modules"),
+    )
+    contain_args: list[bool] = []
+
+    def fake_scan(providers, filters, now, *, contain=True):
+        contain_args.append(contain)
+        return Report(
+            entries=[worktree, inside, outside], scanned_at=now, hostname="h", platform="darwin"
+        )
+
+    monkeypatch.setattr(routes_clean.discovery, "scan", fake_scan)
+    app = _build(tmp_path, monkeypatch)
+    async with AsyncClient(
+        transport=ASGITransport(app=app), base_url="http://testserver"
+    ) as client:
+        r = await client.post(
+            "/api/clean/jobs",
+            json={"entry_ids": ["node:inside", "git-worktrees:feature", "node:outside"]},
+            headers={"Host": "testserver"},
+        )
+        assert r.status_code == 200
+        runner = app.state.runner_registry.active()
+        assert [e.id for e in runner.report.entries] == ["git-worktrees:feature", "node:outside"]
+        await runner.cancel()
+    assert contain_args == [False]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/web -q`
Expected: `test_filtered_scans_never_write_an_auto_snapshot` and `test_cleanup_scan_is_uncontained_and_drops_contents_of_selected_worktrees` fail with `AssertionError`.

- [ ] **Step 3: Implement**

Apply this change to `src/devdoctor/web/routes_scan.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/web/routes_scan.py b/src/devdoctor/web/routes_scan.py
--- a/src/devdoctor/web/routes_scan.py
+++ b/src/devdoctor/web/routes_scan.py
@@ -60,12 +60,18 @@ def scan(
     providers_list = registry.load_providers(request.app.state.shell)
     report = discovery.scan(providers_list, filters, datetime.now(UTC))
     storage: StorageBackend = request.app.state.storage
-    if filters.min_size_bytes == 0 and filters.risks is None and filters.providers is None:
+    # Only an unfiltered scan may be stored: a filtered report's totals cover part of
+    # the disk, and would read as a drop in history (#103).
+    if filters.is_unfiltered:
         try:
             storage.write_disk_dashboard_summary(report)
         except OSError as exc:
             logger.warning("scan: failed to write dashboard summary: %s", exc)
-    if snapshot and _should_write_auto_snapshot(storage, snapshot_min_interval_ms):
+    if (
+        snapshot
+        and filters.is_unfiltered
+        and _should_write_auto_snapshot(storage, snapshot_min_interval_ms)
+    ):
         auto_report = dataclasses.replace(report, kind=SnapshotKind.AUTO)
         try:
             storage.write_disk_snapshot(auto_report)
```

Apply this change to `src/devdoctor/web/routes_clean.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/web/routes_clean.py b/src/devdoctor/web/routes_clean.py
--- a/src/devdoctor/web/routes_clean.py
+++ b/src/devdoctor/web/routes_clean.py
@@ -10,6 +10,7 @@ from sse_starlette.sse import EventSourceResponse
 from starlette.responses import JSONResponse, Response

 from devdoctor import discovery, registry
+from devdoctor.containment import drop_contents_of_selected_worktrees
 from devdoctor.types import CleanupOpts, ScanFilters, ShellResult
 from devdoctor.web.cleanup_runner import CleanupRunner
 from devdoctor.web.models import CleanJobCreate, ConfirmAnswer, PromptAnswer
@@ -21,7 +22,9 @@ router = APIRouter(prefix="/api/clean")
 @router.post("/jobs")
 async def start_job(body: CleanJobCreate, request: Request) -> Response:
     providers_list = registry.load_providers(request.app.state.shell)
-    report = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
+    # Uncontained: this scan establishes current state for the selection, so every id
+    # a filtered view could have shown still exists (spec §6.4).
+    report = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC), contain=False)
     # Entry ids are globally unique (namespaced "{provider}:{id}" in
     # discovery.scan), so selecting by bare id can never cross providers.
     known_ids = {e.id for e in report.entries}
@@ -32,8 +35,12 @@ async def start_job(body: CleanJobCreate, request: Request) -> Response:
             content={"error": {"code": "unknown_entry", "ids": unknown}},
         )
     # Filter the report down to just the selected entries — cleanup walks candidates from there.
+    # Removing a selected worktree deletes its contents, so selected entries inside it
+    # are dropped rather than cleaned (and counted) a second time.
     selected = set(body.entry_ids)
-    report.entries = [e for e in report.entries if e.id in selected]
+    report.entries = drop_contents_of_selected_worktrees(
+        [e for e in report.entries if e.id in selected]
+    )

     registry_obj = request.app.state.runner_registry

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/web -q`
Expected: no failures.

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add tests/web/test_routes_scan.py tests/web/test_routes_clean.py src/devdoctor/web/routes_scan.py src/devdoctor/web/routes_clean.py
git commit -m "fix(web): scan cleanup selections uncontained and store only unfiltered scans" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Provider hardening before registration

Deferred findings from PR 2's reviews that must land before users see the provider.

**Files:**
- Modify: `src/devdoctor/providers/_worktree_states.py`
- Modify: `src/devdoctor/providers/_git_queries.py`
- Modify: `src/devdoctor/providers/git_worktrees.py`
- Modify: `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md`
- Test (modify): `tests/test_worktree_states.py`
- Test (modify): `tests/test_git_queries.py`
- Test (modify): `tests/test_git_worktrees_provider.py`
- Test (modify): `tests/test_project_index_git_candidates.py`

**Interfaces:**
- Consumes: the PR 2 provider modules (`_worktree_states.py`, `_git_queries.py`, `git_worktrees.py`) and the `git_fixture` fixture.
- Produces: `WorktreeFacts.ownership_ok` (renamed from `toplevel_ok`); `advice_message(WorktreeState.DIRTY, ...)` raises `ValueError` without `status`; new diagnostic texts (below); `worktree_belongs_to` never reads a non-regular `gitdir` file.

- [ ] **Step 1: Write the failing tests**

Apply this change to `tests/test_worktree_states.py` (for example with `git apply`):

```diff
diff --git a/tests/test_worktree_states.py b/tests/test_worktree_states.py
--- a/tests/test_worktree_states.py
+++ b/tests/test_worktree_states.py
@@ -20,30 +20,30 @@ DIRTY = StatusCounts(modified=7, untracked=3)
     ("facts", "expected"),
     [
         pytest.param(
-            WorktreeFacts(toplevel_ok=False, locked=True, default_branch=None),
+            WorktreeFacts(ownership_ok=False, locked=True, default_branch=None),
             WorktreeState.BROKEN_POINTER,
             id="broken-pointer-wins-over-everything",
         ),
         pytest.param(
             WorktreeFacts(
-                toplevel_ok=False, locked=True, default_branch=None, failure="timed out after 30 s"
+                ownership_ok=False, locked=True, default_branch=None, failure="timed out after 30 s"
             ),
             WorktreeState.GIT_ERROR,
             id="unverified-ownership-git-error-wins-over-locked",
         ),
         pytest.param(
-            WorktreeFacts(toplevel_ok=True, locked=True, default_branch=None),
+            WorktreeFacts(ownership_ok=True, locked=True, default_branch=None),
             WorktreeState.LOCKED,
             id="locked-wins-over-no-default-branch",
         ),
         pytest.param(
-            WorktreeFacts(toplevel_ok=True, locked=False, default_branch=None, failure="boom"),
+            WorktreeFacts(ownership_ok=True, locked=False, default_branch=None, failure="boom"),
             WorktreeState.NO_DEFAULT_BRANCH,
             id="no-default-branch-wins-over-git-error",
         ),
         pytest.param(
             WorktreeFacts(
-                toplevel_ok=True,
+                ownership_ok=True,
                 locked=False,
                 default_branch="origin/main",
                 failure="timed out after 30 s",
@@ -53,13 +53,13 @@ DIRTY = StatusCounts(modified=7, untracked=3)
             id="git-error-wins-over-not-integrated",
         ),
         pytest.param(
-            WorktreeFacts(toplevel_ok=True, locked=False, default_branch="origin/main"),
+            WorktreeFacts(ownership_ok=True, locked=False, default_branch="origin/main"),
             None,
             id="integration-still-needed",
         ),
         pytest.param(
             WorktreeFacts(
-                toplevel_ok=True,
+                ownership_ok=True,
                 locked=False,
                 default_branch="origin/main",
                 integration=Integration.NOT_INTEGRATED,
@@ -70,7 +70,7 @@ DIRTY = StatusCounts(modified=7, untracked=3)
         ),
         pytest.param(
             WorktreeFacts(
-                toplevel_ok=True,
+                ownership_ok=True,
                 locked=False,
                 default_branch="origin/main",
                 integration=Integration.INTEGRATED,
@@ -80,7 +80,7 @@ DIRTY = StatusCounts(modified=7, untracked=3)
         ),
         pytest.param(
             WorktreeFacts(
-                toplevel_ok=True,
+                ownership_ok=True,
                 locked=False,
                 default_branch="origin/main",
                 integration=Integration.INTEGRATED,
@@ -91,7 +91,7 @@ DIRTY = StatusCounts(modified=7, untracked=3)
         ),
         pytest.param(
             WorktreeFacts(
-                toplevel_ok=True,
+                ownership_ok=True,
                 locked=False,
                 default_branch="origin/main",
                 integration=Integration.INTEGRATED,
@@ -217,3 +217,8 @@ def test_advice_messages_match_the_spec(state, kwargs, expected):
 def test_integrated_has_no_advice():
     with pytest.raises(ValueError, match="not an advice state"):
         advice_message(WorktreeState.INTEGRATED, repository=REPO)
+
+
+def test_dirty_advice_needs_the_status_counts():
+    with pytest.raises(ValueError, match="status counts"):
+        advice_message(WorktreeState.DIRTY, repository=REPO, default_branch="origin/main")
```

Apply this change to `tests/test_git_queries.py` (for example with `git apply`):

```diff
diff --git a/tests/test_git_queries.py b/tests/test_git_queries.py
--- a/tests/test_git_queries.py
+++ b/tests/test_git_queries.py
@@ -1,5 +1,6 @@
 import os
 import shutil
+import threading
 from pathlib import Path

 import pytest
@@ -576,3 +577,21 @@ def test_real_default_branch_ignores_a_tag_named_like_a_remote_ref(git_fixture,
     default = resolve_default_branch(REAL_GIT, repo.path)
     assert default is not None
     assert (default.name, default.commit) == ("origin/master", base)
+
+
+def test_real_ownership_check_does_not_block_on_a_fifo_backlink(git_fixture, tmp_path):
+    repo = git_fixture.repository(tmp_path / "app")
+    worktree = repo.add_worktree(tmp_path / "feature", "feature")
+    backlink = repo.path / ".git" / "worktrees" / "feature" / "gitdir"
+    backlink.unlink()
+    os.mkfifo(backlink)
+    outcome: list[bool] = []
+    check = threading.Thread(
+        target=lambda: outcome.append(
+            worktree_belongs_to(REAL_GIT, worktree.path, repo.path / ".git")
+        ),
+        daemon=True,
+    )
+    check.start()
+    check.join(timeout=10)
+    assert outcome == [False]
```

Apply this change to `tests/test_git_worktrees_provider.py` (for example with `git apply`):

```diff
diff --git a/tests/test_git_worktrees_provider.py b/tests/test_git_worktrees_provider.py
--- a/tests/test_git_worktrees_provider.py
+++ b/tests/test_git_worktrees_provider.py
@@ -258,8 +258,8 @@ def test_missing_worktree_has_no_entry_and_suggests_prune(app, projects):

     assert entries == []
     assert provider.diagnostics == [
-        f"git-worktrees: 1 registered worktree(s) of {app.path} no longer exist; "
-        f'run "git -C {app.path} worktree prune"'
+        f"git-worktrees: 1 registered worktree(s) of {app.path} are missing or no longer "
+        f'valid; run "git -C {app.path} worktree prune"'
     ]


@@ -376,8 +376,17 @@ def test_git_before_2_36_reports_nothing():
     entries, provider = _discover(shell)
     assert entries == []
     assert provider.diagnostics == [
-        "git-worktrees: worktree listing needs git 2.36 and git 2.35.8 could not be "
-        "confirmed to support it; no worktrees reported"
+        "git-worktrees: worktree listing needs git 2.36, found git 2.35.8; no worktrees reported"
+    ]
+
+
+def test_unknown_git_version_reports_nothing():
+    version = ("git", "--no-optional-locks", "-C", "/", "version")
+    shell = FakeShell(responses={version: ShellResult(1, "", "boom\n")})
+    entries, provider = _discover(shell)
+    assert entries == []
+    assert provider.diagnostics == [
+        "git-worktrees: could not determine the git version; no worktrees reported"
     ]


@@ -657,3 +666,63 @@ def test_discovery_runs_no_writing_command(app, projects):
         assert env is not None
         if env.get("GIT_OBJECT_DIRECTORY") is not None:
             assert "merge-tree" in argv, argv
+
+
+def test_unregistered_broken_pointer_is_unverifiable(git_fixture, tmp_path, projects):
+    repo = git_fixture.repository(tmp_path / "elsewhere" / "app")
+    worktree = repo.add_worktree(projects / "wt" / "orphan", "orphan")
+    shutil.rmtree(repo.path)
+
+    entry = _entry(_discover()[0], worktree.path)
+
+    assert entry.label == "app/orphan · unverifiable"
+    _assert_advice_shape(entry)
+
+
+def test_worktree_of_a_bare_repository_is_classified_without_diagnostics(
+    git_fixture, tmp_path, projects
+):
+    source = git_fixture.repository(tmp_path / "source")
+    bare = projects / "bare.git"
+    subprocess.run(
+        ["git", "clone", "--bare", "-q", str(source.path), str(bare)],
+        check=True,
+        capture_output=True,
+    )
+    worktree = projects / "wt" / "feature"
+    subprocess.run(
+        ["git", "-C", str(bare), "worktree", "add", "-q", "-b", "feature", str(worktree), "main"],
+        check=True,
+        capture_output=True,
+    )
+
+    entries, provider = _discover()
+
+    assert _entry(entries, worktree).label == "bare.git/feature · no default branch"
+    assert provider.diagnostics == []
+
+
+def test_worktree_on_an_unborn_branch_is_a_git_error(app, projects):
+    version = GitRunner(RealShell()).version()
+    if version is None or version < (2, 42, 0):
+        pytest.skip("git worktree add --orphan needs git 2.42")
+    app.publish()
+    worktree = projects / "wt" / "empty"
+    app.git("worktree", "add", "-q", "--orphan", "-b", "empty", str(worktree))
+
+    entry = _entry(_discover()[0], worktree)
+
+    assert entry.label == "app/empty · git error"
+    assert entry.risk is Risk.DANGEROUS
+
+
+def test_repository_reached_by_the_walk_and_a_pointer_is_listed_once(app, projects):
+    worktree = app.add_worktree(projects / "wt" / "feature", "feature")
+    _merge(app, worktree)
+    app.publish()
+    shell = RecordingShell()
+
+    _discover(shell)
+
+    listings = [argv for argv, _ in shell.calls if argv[4:6] == ("worktree", "list")]
+    assert len(listings) == 1
```

Apply this change to `tests/test_project_index_git_candidates.py` (for example with `git apply`):

```diff
diff --git a/tests/test_project_index_git_candidates.py b/tests/test_project_index_git_candidates.py
--- a/tests/test_project_index_git_candidates.py
+++ b/tests/test_project_index_git_candidates.py
@@ -127,3 +127,16 @@ def test_ignores_a_git_file_whose_gitdir_contains_a_nul_byte(tmp_path, monkeypat
     odd = _mkdir(root / "odd")
     (odd / ".git").write_text("gitdir: /tmp/a\0b/.git/worktrees/x\n")
     assert _git_candidates(root, monkeypatch).pointers == ()
+
+
+def test_symlinked_git_directories_and_folder_children_are_not_recorded(tmp_path, monkeypatch):
+    root = tmp_path / "projects"
+    linked = _mkdir(root / "linked")
+    (linked / ".git").symlink_to(_mkdir(tmp_path / "elsewhere" / ".git"))
+    folder = _mkdir(root / "repo" / ".worktrees")
+    (folder / "linked-child").symlink_to(_mkdir(tmp_path / "elsewhere" / "child"))
+
+    candidates = _git_candidates(root, monkeypatch)
+
+    assert linked not in candidates.repositories
+    assert candidates.folder_children == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_worktree_states.py tests/test_git_queries.py tests/test_git_worktrees_provider.py tests/test_project_index_git_candidates.py -q`
Expected: collection error in `tests/test_worktree_states.py`, `TypeError: WorktreeFacts.__init__() got an unexpected keyword argument 'ownership_ok'`. Run without that file, the other three also fail: the old diagnostic texts, and `test_real_ownership_check_does_not_block_on_a_fifo_backlink` after its 10 s join timeout.

- [ ] **Step 3: Implement**

Apply this change to `src/devdoctor/providers/_worktree_states.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/providers/_worktree_states.py b/src/devdoctor/providers/_worktree_states.py
--- a/src/devdoctor/providers/_worktree_states.py
+++ b/src/devdoctor/providers/_worktree_states.py
@@ -39,12 +39,12 @@ class WorktreeFacts:
     ``status`` only once the worktree is known to be integrated. ``failure`` records
     the first git call that failed.

-    ``toplevel_ok`` is whether the directory was shown to still belong to its
+    ``ownership_ok`` is whether the directory was shown to still belong to its
     registered worktree. When it is false, ``failure`` says whether git could not
     answer (a git error) or answered that it does not (a broken pointer).
     """

-    toplevel_ok: bool
+    ownership_ok: bool
     locked: bool
     default_branch: str | None
     failure: str | None = None
@@ -55,7 +55,7 @@ class WorktreeFacts:
 # One return per state keeps the code in the spec's first-match order.
 def classify(facts: WorktreeFacts) -> WorktreeState | None:  # noqa: PLR0911
     """Return the first matching state (spec §5.1), or ``None`` if more facts are needed."""
-    if not facts.toplevel_ok:
+    if not facts.ownership_ok:
         return WorktreeState.BROKEN_POINTER if facts.failure is None else WorktreeState.GIT_ERROR
     if facts.locked:
         return WorktreeState.LOCKED
@@ -132,11 +132,11 @@ def advice_message(
             "providers report can still be cleaned individually."
         )
     elif state is WorktreeState.DIRTY:
-        modified = status.modified if status else 0
-        untracked = status.untracked if status else 0
+        if status is None:
+            raise ValueError("advice for uncommitted changes needs the status counts")
         message = (
-            f"Integrated into {default_branch}, but has {modified} modified and "
-            f"{untracked} untracked files. Commit, stash or discard them first."
+            f"Integrated into {default_branch}, but has {status.modified} modified and "
+            f"{status.untracked} untracked files. Commit, stash or discard them first."
         )
     elif state is WorktreeState.UNVERIFIABLE:
         message = (
```

Apply this change to `src/devdoctor/providers/_git_queries.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/providers/_git_queries.py b/src/devdoctor/providers/_git_queries.py
--- a/src/devdoctor/providers/_git_queries.py
+++ b/src/devdoctor/providers/_git_queries.py
@@ -199,6 +199,18 @@ def check_integration(
     return Integration.NOT_INTEGRATED


+def _read_backlink(path: Path) -> str | None:
+    """The first line of a worktree's ``gitdir`` file, or None if it cannot be trusted."""
+    # Only a regular file: reading a FIFO placed there would block the worker forever.
+    if not path.is_file():
+        return None
+    try:
+        line = path.read_text(encoding="utf-8", errors="replace").partition("\n")[0]
+    except OSError:
+        return None
+    return line if line and "\0" not in line else None
+
+
 def worktree_belongs_to(git: GitRunner, worktree: Path, common_dir: Path) -> bool:
     """Whether ``worktree`` is still the linked worktree of the repository at ``common_dir``.

@@ -215,15 +227,11 @@ def worktree_belongs_to(git: GitRunner, worktree: Path, common_dir: Path) -> boo
     common = os.path.realpath(common_dir)
     if os.path.realpath(pointer.gitdir.parent.parent) != common:
         return False
-    try:
-        back = (pointer.gitdir / "gitdir").read_text(encoding="utf-8", errors="replace")
-    except OSError:
-        return False
+    back = _read_backlink(pointer.gitdir / "gitdir")
     # git writes an absolute path, or one relative to the git directory (--relative-paths).
-    back = back.partition("\n")[0]
-    if not back or "\0" in back:
-        return False
-    if os.path.realpath(pointer.gitdir / back) != os.path.realpath(worktree / ".git"):
+    if back is None or os.path.realpath(pointer.gitdir / back) != os.path.realpath(
+        worktree / ".git"
+    ):
         return False
     result = git.run(
         worktree, ["rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"]
```

Apply this change to `src/devdoctor/providers/git_worktrees.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/providers/git_worktrees.py b/src/devdoctor/providers/git_worktrees.py
--- a/src/devdoctor/providers/git_worktrees.py
+++ b/src/devdoctor/providers/git_worktrees.py
@@ -90,11 +90,16 @@ class GitWorktreeProvider(Provider):

     def discover(self) -> list[Entry]:
         version = self._git.version()
+        if version is None:
+            self.diagnostics.append(
+                "git-worktrees: could not determine the git version; no worktrees reported"
+            )
+            return []
         if not supports_worktree_list_z(version):
-            found = "the git version" if version is None else "git " + ".".join(map(str, version))
+            found = ".".join(map(str, version))
             self.diagnostics.append(
-                f"git-worktrees: worktree listing needs git 2.36 and {found} could not be "
-                "confirmed to support it; no worktrees reported"
+                f"git-worktrees: worktree listing needs git 2.36, found git {found}; "
+                "no worktrees reported"
             )
             return []
         objects_dir = (
@@ -154,8 +159,8 @@ class GitWorktreeProvider(Provider):
             linked.append(record)
         if stale:
             self.diagnostics.append(
-                f"git-worktrees: {stale} registered worktree(s) of {repository} no longer "
-                f'exist; run "git -C {repository} worktree prune"'
+                f"git-worktrees: {stale} registered worktree(s) of {repository} are missing "
+                f'or no longer valid; run "git -C {repository} worktree prune"'
             )
         return linked

@@ -193,9 +198,9 @@ class GitWorktreeProvider(Provider):
     ) -> tuple[WorktreeState, WorktreeFacts]:
         """Gather facts in spec §5.1 order until one state matches."""
         default = repository.default
-        toplevel_ok, failure = self._ownership(repository, record)
+        ownership_ok, failure = self._ownership(repository, record)
         facts = WorktreeFacts(
-            toplevel_ok=toplevel_ok,
+            ownership_ok=ownership_ok,
             locked=record.locked,
             default_branch=default.name if default else None,
             failure=failure,
```

Apply this change to `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` (for example with `git apply`):

```diff
diff --git a/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md b/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
--- a/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
+++ b/docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
@@ -230,10 +230,10 @@ Registered worktrees are checked in order, and the first match wins.
 |---|---|---|---|
 | 1 | Primary worktree | first porcelain record | none |
 | 2 | Missing, prunable or bare | porcelain `prunable` or `bare`, or the directory is absent | none; one diagnostic per repository suggesting `git -C <repo> worktree prune` |
-| 3 | Broken pointer | the directory no longer belongs to this worktree: `<worktree>/.git` is missing or is not a worktree pointer; the pointer's gitdir does not exist; the gitdir is not inside the repository's common git dir, or its `gitdir` file does not name `<worktree>/.git`; or `rev-parse --path-format=absolute --show-toplevel --git-common-dir` in the worktree names a different toplevel or common dir. Paths compare after resolving symlinks. If that `rev-parse` fails or times out with the pointer intact, the worktree is state 6 instead | advice |
+| 3 | Broken pointer | the directory no longer belongs to this worktree: `<worktree>/.git` is missing or is not a worktree pointer; the pointer's gitdir does not exist; the gitdir is not `<common git dir>/worktrees/<name>`, or its `gitdir` file does not name `<worktree>/.git`; or `rev-parse --path-format=absolute --show-toplevel --git-common-dir` in the worktree names a different toplevel or common dir. Paths compare after resolving symlinks. If that `rev-parse` fails or times out with the pointer intact, the worktree is state 6 instead | advice |
 | 4 | Locked | porcelain `locked [reason]` | advice |
 | 5 | Default branch unresolvable | §4.4 | advice |
-| 6 | git error | the state 3 `rev-parse` (pointer intact), `--git-common-dir` for the repository, or a later call (`merge-tree`, `status`) exits non-zero or times out | advice |
+| 6 | git error | the state 3 `rev-parse` (pointer intact), `--git-common-dir` for the repository, or a later call (`merge-tree` or `merge-base --is-ancestor`, `status`) exits non-zero or times out | advice |
 | 7 | Not integrated | §4.4 | advice |
 | 8 | Integrated, dirty | `status --porcelain --untracked-files=normal` produces output | advice |
 | 9 | Integrated, clean | all checks pass | **reclaimable** |
@@ -409,6 +409,7 @@ containment rules.
 |---|---|
 | `git` not on `PATH` | provider unavailable, via `required_binary` |
 | `git` older than 2.36 (no `worktree list -z`) | no worktree entries; one diagnostic naming the installed version |
+| The `git` version cannot be determined | no worktree entries; one diagnostic |
 | A per-worktree git call exits non-zero or times out | that worktree is a git error (§5.1 state 6), including the ownership `rev-parse` when its `.git` pointer is intact; a worktree whose ownership fails the pointer checks is a broken pointer (state 3) without that call; the provider continues |
 | A repository's `rev-parse --git-common-dir` fails | every worktree of that repository is a git error with that failure; no integration or status check runs for them |
 | A repository's `worktree list` fails | one diagnostic for that repository; its worktrees are not reported |
@@ -541,6 +542,14 @@ should land no later than PR 3.
 - **Double sizing.** Contents of a reclaimable worktree are sized by their own
   providers and again as part of the worktree before containment removes them
   (#92).
+- **Worktree paths containing a newline.** The ownership `rev-parse` prints one
+  path per line, so such a worktree reads as a broken pointer with the "does not
+  point back" advice even when its pointer is intact. It is never reclaimable.
+- **Relative pointers under symlinked directories.** A relative `gitdir:` line is
+  normalised without resolving symlinks, so a pointer under a symlinked scan root
+  can name a repository that does not exist, and its worktree is reported as
+  unverifiable instead of classified. Worktrees are still classified, and removed,
+  only through the repository that registers them.
 - **Commits made between classification and cleanup.** Integration is checked
   against the HEAD read at scan time; if an agent commits in a detached,
   integrated worktree before `git worktree remove` runs, the worktree still
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_worktree_states.py tests/test_git_queries.py tests/test_git_worktrees_provider.py tests/test_project_index_git_candidates.py -q`
Expected: no failures; `test_ci_runs_the_merge_tree_path` skips outside CI.

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_worktree_states.py tests/test_git_queries.py tests/test_git_worktrees_provider.py tests/test_project_index_git_candidates.py src/devdoctor/providers/_worktree_states.py src/devdoctor/providers/_git_queries.py src/devdoctor/providers/git_worktrees.py docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
git commit -m "fix(git-worktrees): harden classification and diagnostics before registration" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Web UI: unmeasured entries are not 0 B (#97)

Registration makes roughly a hundred deliberately unmeasured advice entries visible; the web UI must not render them as empty (#97).

**Files:**
- Modify: `web/src/hooks/useScan.ts`
- Modify: `web/src/components/CacheTable.tsx`
- Create: `web/src/lib/scanRows.ts`
- Modify: `web/src/pages/Scan.tsx`
- Modify: `web/src/components/CleanupWizard/ReviewStep.tsx`
- Test (modify): `web/tests/unit/useScan.test.tsx`
- Test (modify): `web/tests/unit/CacheTable.test.tsx`
- Test (create): `web/tests/unit/scanRows.test.ts`

**Interfaces:**
- Consumes: the `/api/scan` JSON, where an unmeasured entry has `footprint_bytes: null` and `reclaimable_bytes: null` (Tasks 1 and 3).
- Produces:
  - `CacheTableRow.footprint_bytes: number | null` now carries `null` for unmeasured rows; `size_bytes` stays a number (`0` for them).
  - `partitionByMinSize(rows: CacheTableRow[], threshold: number): { visibleRows, hiddenRows, visibleBytes, hiddenBytes }` in `web/src/lib/scanRows.ts`.

- [ ] **Step 1: Write the failing tests**

Apply this change to `web/tests/unit/useScan.test.tsx` (for example with `git apply`):

```diff
diff --git a/web/tests/unit/useScan.test.tsx b/web/tests/unit/useScan.test.tsx
--- a/web/tests/unit/useScan.test.tsx
+++ b/web/tests/unit/useScan.test.tsx
@@ -62,6 +62,29 @@ describe("useScan", () => {
     expect(result.current.data?.rows.length).toBe(3);
   });

+  it("keeps an unmeasured footprint as null instead of substituting size_bytes", async () => {
+    mockApiFetch.mockResolvedValue({
+      entries: [
+        { ...entry("worktree", 0, "dangerous"), footprint_bytes: null, reclaimable_bytes: null },
+        { ...entry("measured", 700, "safe"), footprint_bytes: 700, reclaimable_bytes: 700 },
+        entry("legacy", 300, "safe"),
+      ],
+      scanned_at: "2026-04-25T10:00:00Z",
+      hostname: "h",
+      platform: "darwin",
+      skipped_paths: [],
+    });
+    const { useScan } = await import("@/hooks/useScan");
+    const { result } = renderHook(() => useScan(), { wrapper });
+    await waitFor(() => expect(result.current.data).toBeTruthy());
+    const byId = Object.fromEntries(result.current.data!.rows.map((r) => [r.id, r]));
+    expect(byId.worktree.footprint_bytes).toBeNull();
+    expect(byId.worktree.size_bytes).toBe(0);
+    expect(byId.worktree.reclaimable_bytes).toBeNull();
+    expect(byId.measured.footprint_bytes).toBe(700);
+    expect(byId.legacy.footprint_bytes).toBe(300);
+  });
+
   it("returns 0 totalBytes when every entry is dangerous", async () => {
     mockApiFetch.mockResolvedValue({
       entries: [entry("a", 1000, "dangerous"), entry("b", 2000, "dangerous")],
```

Apply this change to `web/tests/unit/CacheTable.test.tsx` (for example with `git apply`):

```diff
diff --git a/web/tests/unit/CacheTable.test.tsx b/web/tests/unit/CacheTable.test.tsx
--- a/web/tests/unit/CacheTable.test.tsx
+++ b/web/tests/unit/CacheTable.test.tsx
@@ -75,6 +75,40 @@ describe("CacheTable", () => {
     expect(providerCells[1].textContent).toBe("docker");
   });

+  const unmeasured: CacheTableRow = {
+    id: "3",
+    provider: "git-worktrees",
+    label: "app/feature · not integrated",
+    path: "/p/app/.worktrees/feature",
+    size_bytes: 0,
+    footprint_bytes: null,
+    reclaimable_bytes: null,
+    shared_bytes: 0,
+    risk: "dangerous",
+    mtime: null,
+    recipeHint: "echo 'Not integrated into origin/main.'",
+    owner: null,
+    group: null,
+    perms: null,
+  };
+
+  it("renders an unmeasured footprint as a dash, not 0B", () => {
+    render(<CacheTable rows={[unmeasured]} selected={new Set()} onToggle={() => {}} />);
+    expect(screen.getByTitle("Not measured")).toHaveTextContent("—");
+    expect(screen.queryByText("0B")).not.toBeInTheDocument();
+  });
+
+  it("sorts unmeasured rows after measured rows in both directions", () => {
+    render(
+      <CacheTable rows={[unmeasured, ...rows]} selected={new Set()} onToggle={() => {}} />,
+    );
+    const order = () =>
+      screen.getAllByText(/^(docker|uv-cache|git-worktrees)$/).map((cell) => cell.textContent);
+    expect(order()).toEqual(["docker", "uv-cache", "git-worktrees"]);
+    fireEvent.click(screen.getByRole("button", { name: /footprint/i }));
+    expect(order()).toEqual(["uv-cache", "docker", "git-worktrees"]);
+  });
+
   it("sorts alphabetically when the provider header is clicked", () => {
     render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
     fireEvent.click(screen.getByRole("button", { name: /provider/i }));
```

Create `web/tests/unit/scanRows.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { CacheTableRow } from "@/components/CacheTable";
import { partitionByMinSize } from "@/lib/scanRows";

function row(id: string, size: number, footprint: number | null = size): CacheTableRow {
  return {
    id,
    provider: "p",
    label: id,
    path: `/x/${id}`,
    size_bytes: size,
    footprint_bytes: footprint,
    reclaimable_bytes: footprint,
    shared_bytes: 0,
    risk: "safe",
    mtime: null,
    recipeHint: "",
    owner: null,
    group: null,
    perms: null,
  };
}

describe("partitionByMinSize", () => {
  it("shows everything when there is no threshold", () => {
    const rows = [row("a", 10), row("b", 0, null)];
    const result = partitionByMinSize(rows, 0);
    expect(result.visibleRows.map((r) => r.id)).toEqual(["a", "b"]);
    expect(result.hiddenRows).toEqual([]);
    expect(result.visibleBytes).toBe(10);
  });

  it("hides measured rows below the threshold and totals them", () => {
    const result = partitionByMinSize([row("big", 500), row("small", 20)], 100);
    expect(result.visibleRows.map((r) => r.id)).toEqual(["big"]);
    expect(result.hiddenRows.map((r) => r.id)).toEqual(["small"]);
    expect(result.hiddenBytes).toBe(20);
    expect(result.visibleBytes).toBe(500);
  });

  it("never hides an unmeasured row as small", () => {
    const result = partitionByMinSize([row("worktree", 0, null), row("small", 20)], 100);
    expect(result.visibleRows.map((r) => r.id)).toEqual(["worktree"]);
    expect(result.hiddenRows.map((r) => r.id)).toEqual(["small"]);
    expect(result.visibleBytes).toBe(0);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && bunx vitest run tests/unit/useScan.test.tsx tests/unit/CacheTable.test.tsx tests/unit/scanRows.test.ts`
Expected: vitest reports failures: `scanRows.test.ts` cannot resolve `@/lib/scanRows`, and the new `useScan` and `CacheTable` cases fail.

- [ ] **Step 3: Implement**

Apply this change to `web/src/hooks/useScan.ts` (for example with `git apply`):

```diff
diff --git a/web/src/hooks/useScan.ts b/web/src/hooks/useScan.ts
--- a/web/src/hooks/useScan.ts
+++ b/web/src/hooks/useScan.ts
@@ -80,7 +80,11 @@ export function useScan(params: UseScanOptions = {}) {
       const query = qs.toString() ? `?${qs}` : "";
       const raw = await apiFetch<ScanResponse>(`/scan${query}`);
       const rows: CacheTableRow[] = raw.entries.map((e) => {
-        const footprint = e.footprint_bytes ?? e.size_bytes;
+        // null means the provider deliberately left the entry unmeasured (for
+        // example an advice-only git worktree); only a missing field falls back
+        // to size_bytes, for providers that predate explicit usage.
+        const footprint =
+          e.footprint_bytes === undefined ? e.size_bytes : e.footprint_bytes;
         const reclaimable =
           e.reclaimable_bytes !== undefined
             ? e.reclaimable_bytes
@@ -92,7 +96,7 @@ export function useScan(params: UseScanOptions = {}) {
           provider: e.provider,
           label: e.label,
           path: e.path ?? "—",
-          size_bytes: footprint,
+          size_bytes: footprint ?? 0,
           footprint_bytes: footprint,
           reclaimable_bytes: reclaimable,
           shared_bytes: e.shared_bytes ?? 0,
```

Apply this change to `web/src/components/CacheTable.tsx` (for example with `git apply`):

```diff
diff --git a/web/src/components/CacheTable.tsx b/web/src/components/CacheTable.tsx
--- a/web/src/components/CacheTable.tsx
+++ b/web/src/components/CacheTable.tsx
@@ -49,8 +49,13 @@ function makeComparator(
   const sign = dir === "asc" ? 1 : -1;
   return (a, b) => {
     switch (key) {
-      case "size":
+      case "size": {
+        // Unmeasured rows sort after measured ones in either direction.
+        const aUnmeasured = a.footprint_bytes === null;
+        const bUnmeasured = b.footprint_bytes === null;
+        if (aUnmeasured !== bUnmeasured) return aUnmeasured ? 1 : -1;
         return sign * (a.size_bytes - b.size_bytes);
+      }
       case "provider":
         return (
           sign * (a.provider.localeCompare(b.provider) || a.label.localeCompare(b.label))
@@ -305,7 +310,13 @@ function Cell({
     case "size":
       return (
         <div className="text-right tabular-nums font-medium">
-          {humanBytes(row.size_bytes)}
+          {row.footprint_bytes === null ? (
+            <span className="text-text-muted" title="Not measured">
+              —
+            </span>
+          ) : (
+            humanBytes(row.size_bytes)
+          )}
         </div>
       );
     case "risk":
```

Create `web/src/lib/scanRows.ts`:

```ts
import type { CacheTableRow } from "@/components/CacheTable";

export interface MinSizePartition {
  visibleRows: CacheTableRow[];
  hiddenRows: CacheTableRow[];
  visibleBytes: number;
  hiddenBytes: number;
}

/**
 * Split scan rows at the minimum-size setting. Unmeasured rows (footprint null)
 * are never hidden as "small": their size is unknown, not below the threshold.
 */
export function partitionByMinSize(
  rows: CacheTableRow[],
  threshold: number,
): MinSizePartition {
  const isHidden = (row: CacheTableRow) =>
    threshold > 0 && row.footprint_bytes !== null && row.size_bytes < threshold;
  const visibleRows = rows.filter((row) => !isHidden(row));
  const hiddenRows = rows.filter(isHidden);
  const sum = (list: CacheTableRow[]) => list.reduce((total, row) => total + row.size_bytes, 0);
  return {
    visibleRows,
    hiddenRows,
    visibleBytes: sum(visibleRows),
    hiddenBytes: sum(hiddenRows),
  };
}
```

Apply this change to `web/src/pages/Scan.tsx` (for example with `git apply`):

```diff
diff --git a/web/src/pages/Scan.tsx b/web/src/pages/Scan.tsx
--- a/web/src/pages/Scan.tsx
+++ b/web/src/pages/Scan.tsx
@@ -16,6 +16,7 @@ import { cadenceMs, useSettings } from "@/hooks/useSettings";
 import { useScanETA } from "@/hooks/useScanETA";
 import { formatMs, humanBytes, RiskValue, timeAgo } from "@/lib/format";
 import { diskProviderParam } from "@/lib/providerFilters";
+import { partitionByMinSize } from "@/lib/scanRows";

 const RISK_CHIPS: Array<{ key: string; label: string; risks: RiskValue[] }> = [
   { key: "all", label: "all", risks: [] },
@@ -64,18 +65,10 @@ export default function Scan() {
   const [showHiddenRows, setShowHiddenRows] = useState(false);

   const allRows = data?.rows ?? [];
-  const { visibleRows, hiddenRows, hiddenBytes, visibleBytes } = useMemo(() => {
-    const threshold = settings.minSizeBytes;
-    if (threshold <= 0) {
-      const totalBytes = allRows.reduce((a, b) => a + b.size_bytes, 0);
-      return { visibleRows: allRows, hiddenRows: [], hiddenBytes: 0, visibleBytes: totalBytes };
-    }
-    const visible = allRows.filter((r) => r.size_bytes >= threshold);
-    const hidden = allRows.filter((r) => r.size_bytes < threshold);
-    const hBytes = hidden.reduce((a, b) => a + b.size_bytes, 0);
-    const vBytes = visible.reduce((a, b) => a + b.size_bytes, 0);
-    return { visibleRows: visible, hiddenRows: hidden, hiddenBytes: hBytes, visibleBytes: vBytes };
-  }, [allRows, settings.minSizeBytes]);
+  const { visibleRows, hiddenRows, hiddenBytes, visibleBytes } = useMemo(
+    () => partitionByMinSize(allRows, settings.minSizeBytes),
+    [allRows, settings.minSizeBytes],
+  );

   const selectedRows = visibleRows.filter((r) => selected.has(r.id));
   const totalSelected = useMemo(
```

Apply this change to `web/src/components/CleanupWizard/ReviewStep.tsx` (for example with `git apply`):

```diff
diff --git a/web/src/components/CleanupWizard/ReviewStep.tsx b/web/src/components/CleanupWizard/ReviewStep.tsx
--- a/web/src/components/CleanupWizard/ReviewStep.tsx
+++ b/web/src/components/CleanupWizard/ReviewStep.tsx
@@ -39,7 +39,9 @@ export function ReviewStep() {
                 <div className="flex items-center gap-3">
                   <RiskBadge risk={e.risk} />
                   <span className="font-medium text-[12px]">
-                    {humanBytes(e.size_bytes)} footprint
+                    {e.footprint_bytes === null
+                      ? "not measured"
+                      : `${humanBytes(e.size_bytes)} footprint`}
                   </span>
                   <button
                     onClick={() => toggleEnabled(e.id, !on)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && bunx vitest run tests/unit/useScan.test.tsx tests/unit/CacheTable.test.tsx tests/unit/scanRows.test.ts`
Expected: all vitest files pass.

- [ ] **Step 5: Lint and type-check**

Run: `cd web && bun run typecheck && bun run lint`
Expected: `tsc --noEmit` prints no errors; eslint exits 0 (its existing warnings in other files are unchanged).

- [ ] **Step 6: Commit**

```bash
git add web/tests/unit/useScan.test.tsx web/tests/unit/CacheTable.test.tsx web/tests/unit/scanRows.test.ts web/src/hooks/useScan.ts web/src/components/CacheTable.tsx web/src/lib/scanRows.ts web/src/pages/Scan.tsx web/src/components/CleanupWizard/ReviewStep.tsx
git commit -m "fix(web): show unmeasured entries as not measured instead of 0 B" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Registration, end-to-end tests and CHANGELOG

Registration ships in the same PR as containment, so no state of `main` double-counts bytes (spec §9).

**Files:**
- Modify: `src/devdoctor/registry.py`
- Modify: `CHANGELOG.md`
- Test (modify): `tests/test_registry.py`
- Test (create): `tests/test_worktree_containment_e2e.py`

**Interfaces:**
- Consumes: everything above; `GitWorktreeProvider(shell, *, index)` (PR 2).
- Produces: `registry.load_providers` returns `git-worktrees` (family `vcs`), sharing the scan's `ProjectArtifactIndex`.

- [ ] **Step 1: Write the failing tests**

Apply this change to `tests/test_registry.py` (for example with `git apply`):

```diff
diff --git a/tests/test_registry.py b/tests/test_registry.py
--- a/tests/test_registry.py
+++ b/tests/test_registry.py
@@ -39,10 +39,12 @@ def test_registry_includes_expanded_ecosystem_providers():
         "conda-environments",
         "nuget-caches",
         "tox-nox-environments",
+        "git-worktrees",
     } <= providers.keys()
     assert providers["go-caches"].family == "go"
     assert providers["cargo-targets"].family == "rust"
     assert providers["android-sdk-storage"].family == "android"
+    assert providers["git-worktrees"].family == "vcs"


 def test_downloads_provider_is_dangerous_and_advice_only():
```

Create `tests/test_worktree_containment_e2e.py`:

```python
"""End to end: git worktree containment through scan, CLI and web (spec §8.4)."""

from datetime import UTC, datetime

import pytest
from click.testing import CliRunner
from httpx import ASGITransport, AsyncClient

from devdoctor import cleanup, discovery
from devdoctor.cli import build_cli
from devdoctor.ports import RealShell
from devdoctor.providers.git_worktrees import GitWorktreeProvider
from devdoctor.providers.project_artifacts import NodeModulesProvider, ProjectArtifactIndex
from devdoctor.types import CleanupOpts, Risk, ScanFilters
from devdoctor.web.app import build_app


class GitOnlyShell(RealShell):
    """Real subprocesses, but only git counts as installed, so registry scans stay hermetic."""

    def which(self, binary: str) -> str | None:
        return super().which(binary) if binary == "git" else None


@pytest.fixture
def empty_paths_yaml(tmp_path, monkeypatch):
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))


def _integrated_worktree(git_fixture, tmp_path, *, lockfile: bool):
    """A repository with an integrated, clean worktree holding gitignored node_modules."""
    repo = git_fixture.repository(tmp_path / "projects" / "app")
    files = {".gitignore": "node_modules/\n", "package.json": "{}\n"}
    if lockfile:
        files["package-lock.json"] = "{}\n"
    repo.commit("Add package", files)
    worktree = repo.add_worktree(tmp_path / "projects" / "wt" / "feature", "feature")
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    repo.git("merge", "--no-ff", "-q", "-m", "Merge feature", "feature")
    repo.publish()
    package = worktree.path / "node_modules" / "pkg"
    package.mkdir(parents=True)
    (package / "index.js").write_text("x" * 50_000)
    return repo, worktree


@pytest.fixture
def integrated(git_fixture, tmp_path):
    return _integrated_worktree(git_fixture, tmp_path, lockfile=True)


def _scan(filters: ScanFilters | None = None):
    shell = RealShell()
    index = ProjectArtifactIndex()
    providers = [NodeModulesProvider(shell, index=index), GitWorktreeProvider(shell, index=index)]
    return discovery.scan(providers, filters or ScanFilters(), datetime.now(UTC))


def test_contents_of_an_integrated_worktree_are_counted_once(integrated):
    report = _scan()

    [owner] = [e for e in report.entries if e.provider == "git-worktrees"]
    assert owner.risk is Risk.RECLAIMABLE
    assert [e for e in report.entries if e.provider == "node-project-dependencies"] == []
    assert report.total_footprint_bytes() == owner.footprint_bytes
    timings = {timing.name: timing for timing in report.per_provider}
    assert (
        timings["node-project-dependencies"].bytes,
        timings["node-project-dependencies"].entries,
    ) == (0, 0)
    assert sum(timing.bytes for timing in report.per_provider) == owner.size_bytes


def test_a_provider_filter_without_worktrees_contains_nothing(integrated):
    _, worktree = integrated

    report = _scan(ScanFilters(providers=frozenset({"node-project-dependencies"})))

    assert [e.path for e in report.entries] == [worktree.path / "node_modules"]


def test_an_unmeasured_advice_worktree_is_reported(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "projects" / "app")
    worktree = repo.add_worktree(tmp_path / "projects" / "wt" / "feature", "feature")
    worktree.commit("Unmerged work", {"work.txt": "work\n"})
    repo.publish()

    report = _scan()

    [entry] = [e for e in report.entries if e.provider == "git-worktrees"]
    assert entry.label == "app/feature · not integrated"
    assert entry.is_unmeasured


@pytest.mark.asyncio
async def test_an_id_from_a_dangerous_view_can_start_a_cleanup(
    git_fixture, tmp_path, empty_paths_yaml
):
    # Without a lockfile, the worktree's node_modules is dangerous; the worktree is not.
    _integrated_worktree(git_fixture, tmp_path, lockfile=False)
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    app = build_app(GitOnlyShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
    headers = {"Host": "testserver"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        full = (await client.get("/api/scan", headers=headers)).json()
        assert "node-project-dependencies" not in {e["provider"] for e in full["entries"]}

        dangerous = (await client.get("/api/scan?risk=dangerous", headers=headers)).json()
        [entry] = [e for e in dangerous["entries"] if e["provider"] == "node-project-dependencies"]

        response = await client.post(
            "/api/clean/jobs", json={"entry_ids": [entry["id"]]}, headers=headers
        )

        assert response.status_code == 200
        await app.state.runner_registry.active().cancel()


def test_cli_clean_execute_removes_an_integrated_worktree(integrated, empty_paths_yaml):
    repo, worktree = integrated

    result = CliRunner().invoke(build_cli(GitOnlyShell()), ["clean", "--execute"], input="y\ny\n")

    assert result.exit_code == 0, result.output
    assert not worktree.path.exists()
    assert str(worktree.path) not in repo.git("worktree", "list", "--porcelain")


def test_a_worktree_changed_after_the_scan_is_refused_by_git(integrated):
    _, worktree = integrated
    report = _scan()
    (worktree.path / "late.txt").write_text("written after the scan\n")

    results = cleanup.run(
        report,
        shell=RealShell(),
        prompt_choice=lambda entry: "y",
        confirm=lambda summary: True,
        opts=CleanupOpts(execute=True),
    )

    [result] = [r for r in results if r.entry_id.startswith("git-worktrees:")]
    assert result.status == "error"
    assert "untracked" in result.message
    assert worktree.path.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra web pytest tests/test_registry.py tests/test_worktree_containment_e2e.py -q`
Expected: `test_registry_includes_expanded_ecosystem_providers`, `test_an_id_from_a_dangerous_view_can_start_a_cleanup` and `test_cli_clean_execute_removes_an_integrated_worktree` fail.

- [ ] **Step 3: Implement**

Apply this change to `src/devdoctor/registry.py` (for example with `git apply`):

```diff
diff --git a/src/devdoctor/registry.py b/src/devdoctor/registry.py
--- a/src/devdoctor/registry.py
+++ b/src/devdoctor/registry.py
@@ -9,6 +9,7 @@ import yaml
 from devdoctor.ports import Shell
 from devdoctor.providers.base import PathProvider, Provider
 from devdoctor.providers.docker import DockerProvider
+from devdoctor.providers.git_worktrees import GitWorktreeProvider
 from devdoctor.providers.huggingface import HuggingFaceProvider
 from devdoctor.providers.large_files import LargeFilesProvider
 from devdoctor.providers.lm_studio import LMStudioProvider
@@ -49,6 +50,7 @@ _CLASS_PROVIDERS: list[type[Provider]] = [
     CargoTargetsProvider,
     CondaCacheProvider,
     CondaEnvironmentsProvider,
+    GitWorktreeProvider,
     GoCachesProvider,
     HuggingFaceProvider,
     LargeFilesProvider,
@@ -67,15 +69,11 @@ _CLASS_PROVIDERS: list[type[Provider]] = [
 def load_providers(shell: Shell) -> list[Provider]:
     """Load and sort all providers. Fails on duplicate names."""
     project_index = ProjectArtifactIndex()
-    project_provider_types = {
-        NodeModulesProvider,
-        CargoTargetsProvider,
-        AndroidBuildProvider,
-        ToxNoxProvider,
-    }
     providers: list[Provider] = []
     for cls in _CLASS_PROVIDERS:
-        if cls in project_provider_types:
+        # Project-artifact providers (NodeModulesProvider and its subclasses) and the
+        # git worktree provider share one filesystem walk per scan.
+        if issubclass(cls, (NodeModulesProvider, GitWorktreeProvider)):
             providers.append(cls(shell, index=project_index))
         else:
             providers.append(cls(shell))
```

Apply this change to `CHANGELOG.md` (for example with `git apply`):

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -59,6 +59,18 @@ entries under a versioned heading as described in

 ### Added

+- **Git worktrees provider (`git-worktrees`).** Finds the linked worktrees of
+  repositories under the project roots, including worktrees those repositories
+  register elsewhere, and classifies each one without writing to the repository
+  or using the network. A worktree whose changes are already in the default
+  branch (squash and rebase merges included, detected with `git merge-tree`) and
+  that has no uncommitted changes is offered for removal with
+  `git worktree remove`, never `--force`. Every other worktree is reported as
+  advice: not integrated, uncommitted changes, locked, broken pointer, no default
+  branch, git error, or unverifiable. Contents of a removable worktree, such as
+  `node_modules`, virtualenvs and build output, are counted once, under the
+  worktree, instead of again by their own providers.
+  ([#79](https://github.com/katagun/devdoctor/issues/79))
 - **Expanded provider coverage** — added pnpm, Yarn, Bun, bounded
   `node_modules`, Go caches, Cargo dependency/build storage, Xcode/iOS,
   Android SDK/build storage, Conda, NuGet, and tox/nox providers, grouped by
@@ -119,6 +131,13 @@ entries under a versioned heading as described in

 ### Fixed

+- **Filtered web scans no longer save partial auto-snapshots.** A scan with a
+  risk, size or provider filter could be stored as an auto-snapshot and show up
+  in history as a large drop followed by an equal jump. Only unfiltered scans are
+  stored now. ([#103](https://github.com/katagun/devdoctor/issues/103))
+- **The web UI shows unmeasured entries as not measured instead of 0 B.** They
+  sort after measured rows and are never hidden as small by the minimum-size
+  setting. ([#97](https://github.com/katagun/devdoctor/issues/97))
 - **Made Docker volume cleanup precise and version-independent** — unused
   volumes are now listed individually instead of pairing Docker's aggregate
   volume size with version-dependent `docker volume prune` behavior. Anonymous
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev --extra web pytest tests/test_registry.py tests/test_worktree_containment_e2e.py -q`
Expected: no failures.

- [ ] **Step 5: Lint and type-check**

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`, `already formatted`, `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_registry.py tests/test_worktree_containment_e2e.py src/devdoctor/registry.py CHANGELOG.md
git commit -m "feat(git-worktrees): register the provider" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Verify the PR and open it

**Files:** none.

- [ ] **Step 1: Run the full CI mirror**

Run each command from the Commands section, then restore the build placeholder:

```bash
git checkout -- src/devdoctor/web/_static/dist/index.html
```

Expected: ruff `All checks passed!`; ruff format `already formatted`; mypy `Success: no issues found`; pytest with no failures (one CI-only skip); eslint exit 0; `tsc --noEmit` clean; vitest all passing; `vite build` succeeds; `git status` shows no changes.

- [ ] **Step 2: Read-only scan on a real machine**

```bash
uv run --extra dev --extra web devdoctor scan --json > /tmp/devdoctor-pr3-scan.json
python3 -c "import json; d=json.load(open('/tmp/devdoctor-pr3-scan.json')); w=[e for e in d['entries'] if e['provider']=='git-worktrees']; print(len(w), 'worktree entries;', sum(e['risk']=='reclaimable' for e in w), 'reclaimable'); print([m for m in d['diagnostics'] if m.startswith('git-worktrees')])"
```

Expected: worktree entries appear with labels in the `<repo>/<dir> · <state>` form; `scan` changes nothing on disk (it is preview-only). Do not run `clean`.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/git-worktree-containment
gh pr create --base main --title "feat: git worktree containment and registration" --body "$(cat <<'EOF'
PR 3 of 4 for #79, per the design spec (docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §9). User-visible: the `git-worktrees` provider is registered.

## What

- `entry_matches_filters` shared by `Report.filter` and containment; `Entry.is_unmeasured`; `ScanFilters.is_unfiltered`.
- `devdoctor.containment`: entries inside a reclaimable worktree the view shows are removed, so their bytes count once, under the worktree (spec §6.2).
- `discovery.scan(contain=True)` keeps deliberately unmeasured entries, contains, and recomputes every provider total (spec §6.1, §6.3).
- `POST /api/clean/jobs` scans with `contain=False` and drops selected entries inside a selected reclaimable worktree (spec §6.4).
- Only unfiltered web scans write the dashboard summary and auto-snapshots (fixes #103).
- Web UI shows unmeasured entries as not measured, sorts them last and never hides them as small (fixes #97).
- Provider hardening from PR 2's review; spec wording updated.
- `git-worktrees` registered; CHANGELOG.

## Tests

- Containment unit tests (owners, filters, prefixes, symlinks, `path is None`), scan-level totals, and route tests for the cleanup scan and #103.
- End to end on real git: contents counted once; `--provider node-project-dependencies` contains nothing; an unmeasured advice worktree is reported; an id from a `risk=dangerous` view starts a cleanup; `devdoctor clean --execute` removes an integrated worktree and its ignored contents; a worktree changed after the scan is refused by git with its message.
- Vitest for the null footprint, the "—" cell and sort order, and the minimum-size split.

Closes #97. Closes #103.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge once the required checks pass**

The required checks are `Python (lint, types, tests)` and `Web (typecheck, tests, build)`. Also read any CodeQL annotations on the PR and fix new alerts before merging. When everything passes:

```bash
gh pr merge --squash --delete-branch
```

If a check fails, read its log, fix the cause on the branch, and push again. Do not merge on a red check.
