# Column picker + owner/perms columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new columns (`owner`, `perms`) fed by server-side stat data to the Scan page's `CacheTable`, plus a toolbar `columns ▾` dropdown that lets the user show/hide any column (except `provider`). Persistence via `Settings.scanTableHiddenColumns` using the hidden-set pattern so future columns default visible.

**Architecture:** Backend extends the `Entry` dataclass with six additive fields (`uid`, `gid`, `mode`, `owner`, `group`, `perms`) populated via a new `sizer.stat_fields()` helper and surfaced through the existing `/api/scan` JSON. Frontend introduces a single column-registry module (`COLUMNS`) that the `CacheTable` grid template, sort headers, row renderers, and picker UI all read from. All pieces land in order; the last task wires everything together and verifies in the browser.

**Tech Stack:** Python 3.12 + pytest (backend), TypeScript + React 18 + Vitest + Tailwind 4 (frontend). No new dependencies on either side.

**Source spec:** `docs/superpowers/specs/2026-04-23-columns-picker-and-owner-perms-design.md`

**Working directory for every command below:** the worktree the executor creates (e.g. `/Users/shamil/projects/github/katagun/diskdoctor/.worktrees/columns-and-owner`). Backend commands run from the repo root; frontend commands from `web/` inside the worktree.

---

## Task 1: `stat_fields` helper in `sizer` (TDD)

**Files:**
- Modify: `src/diskdoctor/sizer.py`
- Modify: `tests/test_sizer.py`

Adds a pure helper that returns uid/gid/mode plus human-readable owner/group/perms for a path, with None fallback on missing/permission errors. Caches pwd/grp lookups so scanning hundreds of entries costs only a handful of syscalls.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sizer.py` (don't remove existing tests):

```python
import os
import pwd
import stat as stat_mod
from pathlib import Path

from diskdoctor.sizer import StatFields, stat_fields


def test_stat_fields_returns_data_for_existing_path(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("hello")
    fields = stat_fields(target)
    assert fields is not None
    assert isinstance(fields, StatFields)
    # Values should match the live stat.
    st = target.lstat()
    assert fields.uid == st.st_uid
    assert fields.gid == st.st_gid
    assert fields.mode == st.st_mode
    assert fields.owner == pwd.getpwuid(st.st_uid).pw_name
    assert fields.perms == stat_mod.filemode(st.st_mode)


def test_stat_fields_returns_none_for_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert stat_fields(missing) is None


def test_stat_fields_uses_lstat_not_stat(tmp_path: Path) -> None:
    # A symlink to a file with different mode must report the symlink's
    # metadata, not the target's — matches size_path's behavior.
    target = tmp_path / "target.txt"
    target.write_text("data")
    os.chmod(target, 0o600)
    link = tmp_path / "link"
    link.symlink_to(target)
    fields = stat_fields(link)
    assert fields is not None
    # Symlink modes on macOS/Linux are typically 0o755 or 0o777, never 0o600.
    # Asserting strict inequality is fragile, so assert the symlink bit is set.
    assert stat_mod.S_ISLNK(fields.mode)


def test_stat_fields_owner_falls_back_to_numeric_for_unknown_uid(tmp_path: Path) -> None:
    # Pick a uid extremely unlikely to resolve on the host.
    from diskdoctor.sizer import _owner_name, _group_name
    _owner_name.cache_clear()
    _group_name.cache_clear()
    assert _owner_name(999999999) == "999999999"
    assert _group_name(999999999) == "999999999"
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>
uv run pytest tests/test_sizer.py -v 2>&1 | tail
```

Expected: ImportError on `StatFields` / `stat_fields` / `_owner_name` — none of them exist yet.

- [ ] **Step 3: Implement the helper**

Replace the contents of `src/diskdoctor/sizer.py` with (keeping the existing `size_path` intact; this only adds new code):

```python
from __future__ import annotations

import grp
import os
import pwd
import stat as stat_mod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class StatFields:
    """Owner/group/permission metadata for a single filesystem path.

    Names are resolved via pwd/grp with a small LRU cache so a full scan only
    pays a handful of syscalls even across hundreds of entries. `perms` is the
    `ls -l`-style string from stat.filemode (includes the file-type char).
    """

    uid: int
    gid: int
    mode: int
    owner: str
    group: str
    perms: str


@lru_cache(maxsize=256)
def _owner_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


@lru_cache(maxsize=256)
def _group_name(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def stat_fields(path: Path) -> StatFields | None:
    """Return owner/group/perms for `path`, or None on missing / permission
    errors. Uses lstat so symlinks report their own metadata, not the
    target's — matches how size_path handles symlinks.
    """
    try:
        st = path.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    return StatFields(
        uid=st.st_uid,
        gid=st.st_gid,
        mode=st.st_mode,
        owner=_owner_name(st.st_uid),
        group=_group_name(st.st_gid),
        perms=stat_mod.filemode(st.st_mode),
    )


def size_path(root: Path) -> tuple[int, list[Path]]:
    """Compute byte size of `root` recursively.

    Symlink-safe (does not follow), stays on the root's device, and dedupes
    hard-linked / reflinked files by (dev, ino) so a single tree that links
    the same inode from multiple places counts its bytes exactly once.
    Records any paths that errored during walk in the returned `skipped`
    list rather than raising.

    Note: the inode dedup is scoped to a single `size_path` invocation.
    Two providers that separately scan trees sharing hard links will still
    each count the shared bytes — fixing that would require a process-wide
    inode tracker threaded through the scan, which we haven't introduced.
    """
    skipped: list[Path] = []

    try:
        root_stat = root.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        skipped.append(root)
        return 0, skipped

    root_dev = root_stat.st_dev
    total = 0
    seen_inodes: set[tuple[int, int]] = set()

    def on_error(err: OSError) -> None:
        filename = getattr(err, "filename", None)
        skipped.append(Path(filename) if filename else root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=on_error):
        dp = Path(dirpath)

        # Cross-device guard: prune subdirs that live on a different device.
        pruned: list[str] = []
        for d in list(dirnames):
            sub = dp / d
            try:
                if sub.lstat().st_dev != root_dev:
                    pruned.append(d)
            except (FileNotFoundError, PermissionError, OSError):
                skipped.append(sub)
                pruned.append(d)
        for d in pruned:
            dirnames.remove(d)

        for name in filenames:
            p = dp / name
            try:
                st = p.lstat()
            except (FileNotFoundError, PermissionError, OSError):
                skipped.append(p)
                continue
            # Hard-link / reflink dedup: skip bytes we've already counted in
            # this walk. st_nlink > 1 signals the file has other names, but
            # the check is unconditional since the cost is just a set lookup.
            key = (st.st_dev, st.st_ino)
            if key in seen_inodes:
                continue
            seen_inodes.add(key)
            # Actual on-disk usage via st_blocks handles sparse files correctly
            # (e.g. Docker.raw reports 80 GB apparent but uses only megabytes).
            # For non-sparse files st_blocks*512 rounds up to a block boundary,
            # so we cap at st_size to preserve per-byte accuracy for normal files.
            blocks = getattr(st, "st_blocks", 0) * 512
            total += min(st.st_size, blocks) if blocks else st.st_size

    return total, skipped
```

- [ ] **Step 4: Run tests and watch them pass**

Run:
```bash
cd <worktree>
uv run pytest tests/test_sizer.py -v 2>&1 | tail
```

Expected: PASS — all 4 new tests plus any existing ones.

- [ ] **Step 5: Run full backend suite to confirm no regressions**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd <worktree>
git add src/diskdoctor/sizer.py tests/test_sizer.py
git commit -m "feat(sizer): stat_fields helper for owner/group/perms"
```

---

## Task 2: Extend `Entry` + serialization (TDD)

**Files:**
- Modify: `src/diskdoctor/types.py`
- Modify: `tests/test_types.py`

Add six nullable fields to `Entry` and propagate through `Report.to_json` / `Report.from_json`. Older snapshots without these fields continue to deserialize with the fields as `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_types.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.types import Entry, Report, Risk


def _make_entry(**overrides) -> Entry:
    base = {
        "provider": "test",
        "id": "e1",
        "path": Path("/tmp/foo"),
        "label": "/tmp/foo",
        "size_bytes": 100,
        "mtime": 1700000000.0,
        "risk": Risk.SAFE,
        "recipe": ["rm -rf /tmp/foo"],
    }
    base.update(overrides)
    return Entry(**base)


def test_entry_new_fields_default_to_none() -> None:
    e = _make_entry()
    assert e.uid is None
    assert e.gid is None
    assert e.mode is None
    assert e.owner is None
    assert e.group is None
    assert e.perms is None


def test_entry_new_fields_accept_values() -> None:
    e = _make_entry(uid=501, gid=20, mode=16877, owner="shamil", group="staff", perms="drwxr-xr-x")
    assert e.uid == 501
    assert e.gid == 20
    assert e.mode == 16877
    assert e.owner == "shamil"
    assert e.group == "staff"
    assert e.perms == "drwxr-xr-x"


def _make_report(entries: list[Entry]) -> Report:
    return Report(
        entries=entries,
        scanned_at=datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC),
        hostname="test-host",
        platform="darwin",
    )


def test_report_round_trip_preserves_new_fields() -> None:
    e = _make_entry(uid=501, gid=20, mode=16877, owner="shamil", group="staff", perms="drwxr-xr-x")
    raw = _make_report([e]).to_json()
    restored = Report.from_json(raw)
    assert len(restored.entries) == 1
    r = restored.entries[0]
    assert r.uid == 501
    assert r.gid == 20
    assert r.mode == 16877
    assert r.owner == "shamil"
    assert r.group == "staff"
    assert r.perms == "drwxr-xr-x"


def test_report_round_trip_entry_without_stat_fields() -> None:
    e = _make_entry(path=None)  # class-based provider entry (e.g. ollama model)
    raw = _make_report([e]).to_json()
    restored = Report.from_json(raw)
    r = restored.entries[0]
    assert r.uid is None
    assert r.owner is None
    assert r.perms is None


def test_old_snapshot_without_new_fields_deserializes_with_none() -> None:
    # Simulate a snapshot from a pre-feature version: no uid/gid/mode/owner/group/perms keys.
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "provider": "test",
                "id": "e1",
                "path": "/tmp/foo",
                "label": "/tmp/foo",
                "size_bytes": 100,
                "mtime": 1700000000.0,
                "risk": "safe",
                "recipe": ["rm -rf /tmp/foo"],
            }
        ],
        "scanned_at": "2026-04-23T12:00:00+00:00",
        "hostname": "test-host",
        "platform": "darwin",
        "note": None,
        "skipped_paths": [],
    }
    restored = Report.from_json(json.dumps(payload))
    assert len(restored.entries) == 1
    r = restored.entries[0]
    assert r.uid is None
    assert r.gid is None
    assert r.mode is None
    assert r.owner is None
    assert r.group is None
    assert r.perms is None
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>
uv run pytest tests/test_types.py -v 2>&1 | tail
```

Expected: FAIL — `Entry` doesn't accept the new keyword args yet.

- [ ] **Step 3: Extend `Entry`**

In `src/diskdoctor/types.py`, replace the current `Entry` dataclass definition:

```python
@dataclass(frozen=True)
class Entry:
    provider: str
    id: str
    path: Path | None
    label: str
    size_bytes: int
    mtime: float | None
    risk: Risk
    recipe: list[str]
```

with:

```python
@dataclass(frozen=True)
class Entry:
    provider: str
    id: str
    path: Path | None
    label: str
    size_bytes: int
    mtime: float | None
    risk: Risk
    recipe: list[str]
    # Stat-derived fields. Populated when the entry is backed by a real
    # filesystem path; None for class-based providers whose entries are
    # logical identifiers (ollama models, docker images).
    uid: int | None = None
    gid: int | None = None
    mode: int | None = None
    owner: str | None = None  # login name, resolved via pwd.getpwuid
    group: str | None = None  # group name, resolved via grp.getgrgid
    perms: str | None = None  # stat.filemode string, e.g. "drwxr-xr-x"
```

- [ ] **Step 4: Update `Report.to_json`**

In the same file, replace the `serialize_entry` function inside `to_json`:

```python
        def serialize_entry(e: Entry) -> dict[str, object]:
            return {
                "provider": e.provider,
                "id": e.id,
                "path": str(e.path) if e.path is not None else None,
                "label": e.label,
                "size_bytes": e.size_bytes,
                "mtime": e.mtime,
                "risk": e.risk.value,
                "recipe": list(e.recipe),
            }
```

with:

```python
        def serialize_entry(e: Entry) -> dict[str, object]:
            return {
                "provider": e.provider,
                "id": e.id,
                "path": str(e.path) if e.path is not None else None,
                "label": e.label,
                "size_bytes": e.size_bytes,
                "mtime": e.mtime,
                "risk": e.risk.value,
                "recipe": list(e.recipe),
                "uid": e.uid,
                "gid": e.gid,
                "mode": e.mode,
                "owner": e.owner,
                "group": e.group,
                "perms": e.perms,
            }
```

- [ ] **Step 5: Update `Report.from_json`**

Replace the entries list comprehension inside `from_json`:

```python
        entries = [
            Entry(
                provider=e["provider"],
                id=e["id"],
                path=Path(e["path"]) if e["path"] is not None else None,
                label=e["label"],
                size_bytes=e["size_bytes"],
                mtime=e["mtime"],
                risk=Risk(e["risk"]),
                recipe=list(e["recipe"]),
            )
            for e in payload["entries"]
        ]
```

with:

```python
        entries = [
            Entry(
                provider=e["provider"],
                id=e["id"],
                path=Path(e["path"]) if e["path"] is not None else None,
                label=e["label"],
                size_bytes=e["size_bytes"],
                mtime=e["mtime"],
                risk=Risk(e["risk"]),
                recipe=list(e["recipe"]),
                uid=e.get("uid"),
                gid=e.get("gid"),
                mode=e.get("mode"),
                owner=e.get("owner"),
                group=e.get("group"),
                perms=e.get("perms"),
            )
            for e in payload["entries"]
        ]
```

Using `.get(...)` instead of `e["..."]` is deliberate — old snapshots without these keys deserialize to `None`.

- [ ] **Step 6: Run targeted tests and watch them pass**

Run:
```bash
cd <worktree>
uv run pytest tests/test_types.py -v 2>&1 | tail
```

Expected: PASS — all 5 new tests plus any existing ones.

- [ ] **Step 7: Run full backend suite**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS. No existing test should break — existing Entry constructions all use positional args or named args without the new fields, and the new fields default to None.

- [ ] **Step 8: Commit**

```bash
cd <worktree>
git add src/diskdoctor/types.py tests/test_types.py
git commit -m "feat(types): Entry gains uid/gid/mode/owner/group/perms (all optional)

Report.to_json emits them; Report.from_json reads with .get() so old
snapshots without the keys deserialize with None. No schema bump
(purely additive per the existing contract)."
```

---

## Task 3: Populate stat fields in every path-rooted provider

**Files:**
- Modify: `src/diskdoctor/providers/base.py`
- Modify: `src/diskdoctor/providers/huggingface.py`
- Modify: `src/diskdoctor/providers/large_files.py`
- Modify: `src/diskdoctor/providers/venv.py`
- Modify: `src/diskdoctor/providers/lm_studio.py`
- Modify: `src/diskdoctor/providers/ollama.py` (only `_walk_models_dir`; the main `discover` keeps `path=None`)
- Modify: `tests/test_path_provider.py` (add one assertion)

Six Entry construction sites need to look up `stat_fields` on the resolved path and spread the result into the Entry. `DockerProvider` and the main `OllamaProvider.discover` stay as-is (their entries represent logical identifiers with no filesystem path).

- [ ] **Step 1: Add a small helper to spread StatFields into kwargs**

Open `src/diskdoctor/providers/base.py`. At the top (with other imports), add:

```python
from diskdoctor.sizer import size_path, stat_fields
```

Right after the `_ALLOWED_PLATFORMS = frozenset(...)` line (or near the top of `PathProvider`), add this module-level helper function:

```python
def _stat_kwargs(path: _Path) -> dict[str, object]:
    """Return the stat-field kwargs for Entry(...) construction. Returns an
    empty dict when stat fails, so callers can `Entry(..., **_stat_kwargs(p))`
    unconditionally and let Entry's defaults (None) fill in.
    """
    fields = stat_fields(path)
    if fields is None:
        return {}
    return {
        "uid": fields.uid,
        "gid": fields.gid,
        "mode": fields.mode,
        "owner": fields.owner,
        "group": fields.group,
        "perms": fields.perms,
    }
```

If `size_path` is already imported from `diskdoctor.sizer`, extend that existing import line rather than adding a duplicate.

- [ ] **Step 2: Wire `PathProvider.discover` to use it**

In `src/diskdoctor/providers/base.py`, inside `PathProvider.discover`, change the Entry construction from:

```python
                entries.append(
                    Entry(
                        provider=self.name,
                        id=str(p),
                        path=p,
                        label=str(p),
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=recipe,
                    )
                )
```

to:

```python
                entries.append(
                    Entry(
                        provider=self.name,
                        id=str(p),
                        path=p,
                        label=str(p),
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=recipe,
                        **_stat_kwargs(p),
                    )
                )
```

- [ ] **Step 3: Apply the same pattern in the other five sites**

For each of the following files, add `from diskdoctor.providers.base import _stat_kwargs` near the existing imports (or `from diskdoctor.sizer import stat_fields` and inline the spread — whichever keeps the diff smallest for the file), and add `**_stat_kwargs(<path_variable>)` as the final argument to the `Entry(...)` call:

- `src/diskdoctor/providers/huggingface.py` — around the `Entry(...)` call; the path var is `repo`.
- `src/diskdoctor/providers/large_files.py` — path var is `file_path`.
- `src/diskdoctor/providers/venv.py` — path var is `real`.
- `src/diskdoctor/providers/lm_studio.py` — TWO sites: `_scan_legacy` and `_scan_hub`. Both have `model_dir`.
- `src/diskdoctor/providers/ollama.py` — ONLY `_walk_models_dir` (path var is `models`). Leave the main `discover`'s Entry (which has `path=None`) unchanged — that entry is a model identifier, not a filesystem entry, so its stat fields stay None.

For each file's edit, the before-after pattern is:

```python
Entry(
    provider=...,
    id=...,
    path=<path_var>,
    label=...,
    size_bytes=...,
    mtime=...,
    risk=...,
    recipe=...,
)
```

becomes:

```python
Entry(
    provider=...,
    id=...,
    path=<path_var>,
    label=...,
    size_bytes=...,
    mtime=...,
    risk=...,
    recipe=...,
    **_stat_kwargs(<path_var>),
)
```

Use whatever import style is already in the file — if the file already imports from `diskdoctor.providers.base` for other reasons, add `_stat_kwargs` to that import. Otherwise add the import.

- [ ] **Step 4: Add one test assertion proving the end-to-end wire works**

In `tests/test_path_provider.py`, find any existing test that asserts on the shape of an emitted `Entry`. Add one new test below it:

```python
def test_path_provider_entry_includes_stat_fields(tmp_path: Path) -> None:
    """Discovered entries should carry owner/group/perms populated from the
    resolved path. Verifies the provider-base helper is wired up correctly."""
    import os
    import pwd
    from diskdoctor.ports import Shell
    from diskdoctor.providers.base import PathProvider
    from diskdoctor.types import Risk

    class _NoopShell:
        def run(self, argv, *, check=True):  # pragma: no cover - unused
            raise AssertionError("unexpected shell call")

        def which(self, name):  # pragma: no cover - unused
            return None

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "file.bin").write_bytes(b"payload")

    platform_tag = "darwin" if os.uname().sysname == "Darwin" else "linux"
    provider = PathProvider(
        shell=_NoopShell(),
        name="test-cache",
        description="tmp cache",
        platforms=(platform_tag,),
        risk=Risk.SAFE,
        raw_paths=(str(cache_dir),),
        recipe_template=["rm -rf {path}"],
    )
    entries = provider.discover()
    assert len(entries) == 1
    e = entries[0]
    st = cache_dir.lstat()
    assert e.uid == st.st_uid
    assert e.gid == st.st_gid
    assert e.mode == st.st_mode
    assert e.owner == pwd.getpwuid(st.st_uid).pw_name
    assert e.perms is not None
    assert e.perms.startswith("d")  # directory
```

If `Shell` is imported from `diskdoctor.ports`, use the real import; otherwise adjust to the existing pattern in the file. The goal is one test that constructs a `PathProvider` against a real tempdir and asserts uid/gid/mode/owner/perms flowed through.

- [ ] **Step 5: Run the targeted tests**

Run:
```bash
cd <worktree>
uv run pytest tests/test_path_provider.py -v 2>&1 | tail
```

Expected: PASS (all existing tests in the file plus the new one).

- [ ] **Step 6: Run the full backend suite**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS. Existing provider tests shouldn't care about the new fields — they construct `Entry` with keyword args that don't include uid/gid/mode, relying on the defaults. If any test breaks because it asserts on the exact `Entry(...)` repr or tuple, update that assertion to match the new shape.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add src/diskdoctor/providers/ tests/test_path_provider.py
git commit -m "feat(providers): populate stat fields for path-rooted entries

PathProvider, HuggingFace, LargeFiles, Venv, LmStudio (both scanners),
and OllamaProvider._walk_models_dir all spread stat_fields() output
into Entry construction. DockerProvider and OllamaProvider.discover
stay as path=None — their entries are logical identifiers, not files."
```

---

## Task 4: Column registry module (TDD)

**Files:**
- Create: `web/src/components/CacheTable/columns.ts`
- Create: `web/tests/unit/columns.test.ts`

First frontend task. Defines the shape every downstream hook/component reads from.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/columns.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { COLUMNS, type ColumnId } from "@/components/CacheTable/columns";

describe("COLUMNS registry", () => {
  it("contains every declared ColumnId exactly once", () => {
    const ids: ColumnId[] = ["provider", "size", "risk", "stale", "owner", "perms"];
    const declared = COLUMNS.map((c) => c.id).sort();
    expect(declared).toEqual([...ids].sort());
  });

  it("provider is the only non-hideable column", () => {
    const nonHideable = COLUMNS.filter((c) => !c.hideable).map((c) => c.id);
    expect(nonHideable).toEqual(["provider"]);
  });

  it("every column defaults to visible", () => {
    for (const col of COLUMNS) {
      expect(col.defaultVisible).toBe(true);
    }
  });

  it("only provider/size/risk/stale are sortable (new columns are not)", () => {
    const sortable = COLUMNS.filter((c) => c.sortable).map((c) => c.id).sort();
    expect(sortable).toEqual(["provider", "risk", "size", "stale"]);
  });
});
```

- [ ] **Step 2: Run the test — it fails**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/columns.test.ts
```

Expected: module-resolution failure on `@/components/CacheTable/columns`.

- [ ] **Step 3: Create the registry**

Create `web/src/components/CacheTable/columns.ts`:

```ts
export type ColumnId =
  | "provider"
  | "size"
  | "risk"
  | "stale"
  | "owner"
  | "perms";

export interface ColumnDef {
  id: ColumnId;
  label: string;
  width: string;          // CSS grid track, e.g. "1fr" or "90px"
  sortable: boolean;
  align?: "right";
  hideable: boolean;      // false only for provider (row identifier)
  defaultVisible: boolean;
}

export const COLUMNS: readonly ColumnDef[] = [
  { id: "provider", label: "provider", width: "1fr",  sortable: true,  hideable: false, defaultVisible: true },
  { id: "size",     label: "size",     width: "90px", sortable: true,  align: "right", hideable: true, defaultVisible: true },
  { id: "risk",     label: "risk",     width: "96px", sortable: true,  hideable: true, defaultVisible: true },
  { id: "stale",    label: "stale",    width: "64px", sortable: true,  align: "right", hideable: true, defaultVisible: true },
  { id: "owner",    label: "owner",    width: "80px", sortable: false, hideable: true, defaultVisible: true },
  { id: "perms",    label: "perms",    width: "90px", sortable: false, hideable: true, defaultVisible: true },
] as const;

/** Subset of ColumnId values that can be sorted on. CacheTable's SortKey
 * type is derived from this so the sortable set stays in sync with the
 * registry. */
export type SortKey = "provider" | "size" | "risk" | "stale";
```

- [ ] **Step 4: Run the test and watch it pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/columns.test.ts
```

Expected: PASS — 4 tests.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 91 tests (87 prior + 4 new).

- [ ] **Step 6: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/components/CacheTable/columns.ts web/tests/unit/columns.test.ts
git commit -m "feat(web): column registry module for CacheTable"
```

---

## Task 5: `useHiddenColumns` hook + Settings field (TDD)

**Files:**
- Modify: `web/src/hooks/useSettings.ts`
- Create: `web/src/hooks/useHiddenColumns.ts`
- Create: `web/tests/unit/useHiddenColumns.test.ts`

Extends the existing `Settings` schema with `scanTableHiddenColumns: ColumnId[]` (stored as an array of strings; validated on read). Provides a hook that wraps the settings store and exposes a convenient `{ hiddenColumns, isVisible, setHidden }` interface.

- [ ] **Step 1: Extend the `Settings` type in `useSettings.ts`**

Open `web/src/hooks/useSettings.ts`. Near the top, add:

```ts
import type { ColumnId } from "@/components/CacheTable/columns";
import { COLUMNS } from "@/components/CacheTable/columns";
```

Find the `Settings` interface and add one field:

```ts
export interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
  sidebarWidth: number;
  sidebarExpandedWidth: number;
  scanTableHiddenColumns: ColumnId[];
}
```

Update `DEFAULTS`:

```ts
const DEFAULTS: Settings = {
  minSizeBytes: 0,
  cadence: "live",
  density: "sparse",
  theme: "system",
  sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
  sidebarExpandedWidth: SIDEBAR_DEFAULT_WIDTH,
  scanTableHiddenColumns: [],
};
```

Update `read()` — inside the existing try-block, add a parser for the new field and include it in the final return object. The parser must validate that each string is a known `ColumnId`:

```ts
    const knownColumnIds = new Set<string>(COLUMNS.map((c) => c.id));
    const scanTableHiddenColumns: ColumnId[] =
      Array.isArray(parsed.scanTableHiddenColumns)
        ? parsed.scanTableHiddenColumns.filter(
            (v: unknown): v is ColumnId =>
              typeof v === "string" && knownColumnIds.has(v),
          )
        : DEFAULTS.scanTableHiddenColumns;
```

Then add `scanTableHiddenColumns,` to the object in the `return { ... }` statement inside `read()`.

- [ ] **Step 2: Write the failing hook tests**

Create `web/tests/unit/useHiddenColumns.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useHiddenColumns } from "@/hooks/useHiddenColumns";

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useHiddenColumns", () => {
  it("defaults to every column visible", async () => {
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    expect(result.current.hiddenColumns.size).toBe(0);
    expect(result.current.isVisible("stale")).toBe(true);
    expect(result.current.isVisible("owner")).toBe(true);
  });

  it("setHidden('stale', true) persists to localStorage and hides the column", async () => {
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    act(() => result.current.setHidden("stale", true));
    expect(result.current.isVisible("stale")).toBe(false);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.scanTableHiddenColumns).toContain("stale");
  });

  it("setHidden('stale', false) un-hides and removes from storage", async () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ scanTableHiddenColumns: ["stale"] }),
    );
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    expect(result.current.isVisible("stale")).toBe(false);
    act(() => result.current.setHidden("stale", false));
    expect(result.current.isVisible("stale")).toBe(true);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.scanTableHiddenColumns).not.toContain("stale");
  });

  it("isVisible('provider') is always true even if someone hand-edits it into the hidden set", async () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ scanTableHiddenColumns: ["provider"] }),
    );
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    expect(result.current.isVisible("provider")).toBe(true);
  });

  it("unknown column ids in stored settings are dropped on read", async () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ scanTableHiddenColumns: ["stale", "unknown_column", "owner"] }),
    );
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    // Only known IDs survive the validator.
    expect(result.current.isVisible("stale")).toBe(false);
    expect(result.current.isVisible("owner")).toBe(false);
    // Sanity: other columns are visible.
    expect(result.current.isVisible("size")).toBe(true);
  });
});
```

- [ ] **Step 3: Run the test and watch it fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useHiddenColumns.test.ts
```

Expected: module-resolution failure on `@/hooks/useHiddenColumns`.

- [ ] **Step 4: Create the hook**

Create `web/src/hooks/useHiddenColumns.ts`:

```ts
import { useCallback, useMemo } from "react";
import type { ColumnId } from "@/components/CacheTable/columns";
import { COLUMNS } from "@/components/CacheTable/columns";
import { useSettings } from "./useSettings";

export interface UseHiddenColumnsResult {
  hiddenColumns: ReadonlySet<ColumnId>;
  isVisible: (id: ColumnId) => boolean;
  setHidden: (id: ColumnId, hidden: boolean) => void;
}

const NON_HIDEABLE = new Set<ColumnId>(
  COLUMNS.filter((c) => !c.hideable).map((c) => c.id),
);

export function useHiddenColumns(): UseHiddenColumnsResult {
  const { settings, update } = useSettings();

  const hiddenColumns = useMemo<ReadonlySet<ColumnId>>(
    () => new Set(settings.scanTableHiddenColumns),
    [settings.scanTableHiddenColumns],
  );

  const isVisible = useCallback(
    (id: ColumnId) => {
      // Non-hideable columns are always visible, even if someone hand-edits
      // the stored hidden set.
      if (NON_HIDEABLE.has(id)) return true;
      return !hiddenColumns.has(id);
    },
    [hiddenColumns],
  );

  const setHidden = useCallback(
    (id: ColumnId, hidden: boolean) => {
      if (NON_HIDEABLE.has(id)) return; // ignore attempts to hide provider
      const next = new Set(settings.scanTableHiddenColumns);
      if (hidden) next.add(id);
      else next.delete(id);
      update({ scanTableHiddenColumns: [...next] });
    },
    [settings.scanTableHiddenColumns, update],
  );

  return { hiddenColumns, isVisible, setHidden };
}
```

- [ ] **Step 5: Run targeted + full tests**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useHiddenColumns.test.ts
```

Expected: PASS — 5 tests.

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 96 tests (91 prior + 5 new).

- [ ] **Step 6: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/hooks/useSettings.ts web/src/hooks/useHiddenColumns.ts web/tests/unit/useHiddenColumns.test.ts
git commit -m "feat(web): useHiddenColumns hook + Settings.scanTableHiddenColumns

Hidden-set pattern (like useSelectedProviders) so future columns added
to COLUMNS default visible. provider column is always visible —
isVisible returns true for it unconditionally."
```

---

## Task 6: `ColumnsPicker` component (TDD)

**Files:**
- Create: `web/src/components/ColumnsPicker.tsx`
- Create: `web/tests/unit/ColumnsPicker.test.tsx`

Self-contained dropdown component. Reads `COLUMNS` for what to show and `useHiddenColumns` for current state + toggle.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/ColumnsPicker.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColumnsPicker } from "@/components/ColumnsPicker";

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

function renderPicker() {
  return render(<ColumnsPicker />);
}

describe("ColumnsPicker", () => {
  it("button is collapsed by default", () => {
    renderPicker();
    const btn = screen.getByRole("button", { name: /columns/i });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("clicking the button opens the panel with aria-expanded=true", () => {
    renderPicker();
    const btn = screen.getByRole("button", { name: /columns/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("renders one menuitemcheckbox per column (provider is disabled)", () => {
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const items = screen.getAllByRole("menuitemcheckbox");
    expect(items).toHaveLength(6);
    // Find the provider item specifically and verify disabled.
    const providerItem = items.find((el) => /provider/i.test(el.textContent ?? ""));
    expect(providerItem?.getAttribute("aria-disabled")).toBe("true");
  });

  it("toggling a checkbox persists the change", () => {
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const items = screen.getAllByRole("menuitemcheckbox");
    const staleItem = items.find((el) => /stale/i.test(el.textContent ?? ""))!;
    expect(staleItem.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(staleItem);
    expect(staleItem.getAttribute("aria-checked")).toBe("false");
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.scanTableHiddenColumns).toContain("stale");
  });

  it("clicking the disabled provider item does NOT change state", () => {
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const items = screen.getAllByRole("menuitemcheckbox");
    const providerItem = items.find((el) => /provider/i.test(el.textContent ?? ""))!;
    fireEvent.click(providerItem);
    expect(providerItem.getAttribute("aria-checked")).toBe("true");
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.scanTableHiddenColumns ?? []).not.toContain("provider");
  });

  it("Escape closes the panel and returns aria-expanded to false", () => {
    renderPicker();
    const btn = screen.getByRole("button", { name: /columns/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("click outside closes the panel", () => {
    render(
      <div>
        <ColumnsPicker />
        <div data-testid="outside">outside</div>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/ColumnsPicker.test.tsx
```

Expected: module-resolution failure on `@/components/ColumnsPicker`.

- [ ] **Step 3: Implement the component**

Create `web/src/components/ColumnsPicker.tsx`:

```tsx
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { COLUMNS } from "@/components/CacheTable/columns";
import { useHiddenColumns } from "@/hooks/useHiddenColumns";

export function ColumnsPicker() {
  const { isVisible, setHidden } = useHiddenColumns();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const panelId = useId();

  const close = useCallback(() => {
    setOpen(false);
    // Return focus to the trigger for a11y.
    buttonRef.current?.focus();
  }, []);

  // Escape to close.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  // Click-outside to close.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="px-3 py-1 rounded text-[11px] border border-border text-text-dim hover:text-text hover:border-border-strong transition-colors"
      >
        columns ▾
      </button>
      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="menu"
          aria-label="Toggle columns"
          className="absolute right-0 top-full mt-1 min-w-[180px] bg-bg-elev-1 border border-border rounded shadow-lg z-10 py-1"
        >
          <div className="text-text-muted text-[9.5px] uppercase tracking-widest px-3 py-1.5">
            show columns
          </div>
          {COLUMNS.map((col) => {
            const checked = isVisible(col.id);
            const disabled = !col.hideable;
            return (
              <button
                key={col.id}
                type="button"
                role="menuitemcheckbox"
                aria-checked={checked}
                aria-disabled={disabled || undefined}
                onClick={() => {
                  if (disabled) return;
                  setHidden(col.id, checked);
                }}
                className={`w-full text-left flex items-center gap-2 px-3 py-1.5 text-[11px] ${
                  disabled ? "text-text-muted cursor-not-allowed" : "text-text hover:bg-bg-elev-2"
                }`}
              >
                <span aria-hidden="true" className="inline-block w-3 text-[10px]">
                  {checked ? "☑" : "☐"}
                </span>
                <span>{col.label}</span>
                {disabled && (
                  <span className="text-text-muted text-[9px] ml-auto">locked</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run targeted tests**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/ColumnsPicker.test.tsx
```

Expected: PASS — 7 tests.

- [ ] **Step 5: Run full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 103 tests (96 prior + 7 new).

- [ ] **Step 6: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/components/ColumnsPicker.tsx web/tests/unit/ColumnsPicker.test.tsx
git commit -m "feat(web): ColumnsPicker dropdown with a11y menu semantics

aria-haspopup menu button opens a role=menu panel with one
menuitemcheckbox per column. provider is aria-disabled (locked).
Escape and click-outside both close; Escape returns focus to the
button. Persists via useHiddenColumns."
```

---

## Task 7: Rewrite `CacheTable` to be registry-driven + wire into Scan page

**Files:**
- Modify: `web/src/components/CacheTable.tsx`
- Modify: `web/src/hooks/useScan.ts`
- Modify: `web/src/pages/Scan.tsx`
- Modify: `web/tests/unit/CacheTable.test.tsx`
- Run: `npm run gen:types` (backend must be running)

Connects everything: `CacheTable` reads the column registry and uses `useHiddenColumns` to filter; `useScan` propagates the six new fields to `CacheTableRow`; the `ColumnsPicker` lands in the Scan page toolbar.

Note on `gen:types`: this regenerates `src/api/types.gen.ts` from the running backend's OpenAPI schema. If the backend isn't running during implementation, skip the regen step — the `CacheTableRow` interface is defined locally in `useScan.ts` (not from the generated types), so the frontend works with or without the regen. Do it opportunistically.

- [ ] **Step 1: Extend `CacheTableRow` and `useScan` to carry the new fields**

Open `web/src/hooks/useScan.ts`. Find the `CacheTableRow` interface (or whatever type is used for row data). Add the optional fields:

```ts
export interface CacheTableRow {
  id: string;
  provider: string;
  label: string;
  path: string;
  size_bytes: number;
  risk: RiskValue;
  mtime: number | null;
  recipeHint: string;
  // NEW — present when the entry has a filesystem path; null for class-based
  // provider entries (ollama models, docker images).
  owner: string | null;
  group: string | null;
  perms: string | null;
}
```

Then find the row-mapping inside `useScan`'s query function. It currently does something like:

```ts
rows: entries.map((e) => ({
  id: e.id,
  provider: e.provider,
  label: e.label,
  path: e.path ?? "—",
  size_bytes: e.size_bytes,
  risk: e.risk,
  mtime: e.mtime,
  recipeHint: e.recipe[0] ?? "",
})),
```

Add the three new fields to the mapping:

```ts
rows: entries.map((e) => ({
  id: e.id,
  provider: e.provider,
  label: e.label,
  path: e.path ?? "—",
  size_bytes: e.size_bytes,
  risk: e.risk,
  mtime: e.mtime,
  recipeHint: e.recipe[0] ?? "",
  owner: e.owner ?? null,
  group: e.group ?? null,
  perms: e.perms ?? null,
})),
```

If the mapping structure differs from the above, preserve the surrounding code — only add the three field lines. The exact shape in `useScan.ts` is slightly different if it uses TanStack Query's transform; adjust accordingly without restructuring.

- [ ] **Step 2: Augment `CacheTable.test.tsx` fixtures and add three new tests**

Open `web/tests/unit/CacheTable.test.tsx`. Find the `rows` fixture at the top. Update each row object to include `owner`, `group`, `perms` fields — add `owner: "shamil", group: "staff", perms: "drwxr-xr-x"` to the docker-row fixture and `owner: null, group: null, perms: null` to the uv-cache fixture (or whatever the second row is). This lets the existing tests continue to compile.

Then add these three tests inside the existing `describe("CacheTable", ...)` block:

```tsx
  it("hides the stale column when it's in hiddenColumns", () => {
    // Seed localStorage so useHiddenColumns reports stale as hidden.
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ scanTableHiddenColumns: ["stale"] }),
    );
    const { container } = render(
      <CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />,
    );
    expect(container.textContent?.toLowerCase()).not.toContain("stale");
  });

  it("renders owner and perms cells when fields are populated", () => {
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    expect(screen.getByText("shamil")).toBeInTheDocument();
    expect(screen.getByText("drwxr-xr-x")).toBeInTheDocument();
  });

  it("renders — for owner/perms when those fields are null", () => {
    const onlyNullRow = [{ ...rows[1], id: "null-row" }]; // the fixture whose owner/perms are null
    const { container } = render(
      <CacheTable rows={onlyNullRow} selected={new Set()} onToggle={() => {}} />,
    );
    // The dash character appears in owner AND perms cells.
    const dashes = container.querySelectorAll("*");
    const dashCount = Array.from(dashes).filter((el) => el.textContent === "—").length;
    expect(dashCount).toBeGreaterThanOrEqual(2);
  });
```

Also add `beforeEach(() => localStorage.clear())` at the top of the `describe` block if not already present (this is needed because the new test seeds localStorage).

Also import `__testReloadSettings` from `@/hooks/useSettings` (the existing Sidebar test uses this pattern) and call it in `beforeEach` after `localStorage.clear()` so `useSettings`'s module-level cache re-reads.

- [ ] **Step 3: Run the tests — the new ones fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/CacheTable.test.tsx
```

Expected: the 3 new tests fail (no owner/perms cells rendered; stale column still there). The 7 existing tests might still pass since no grid structure changed yet.

- [ ] **Step 4: Rewrite `CacheTable.tsx` to be registry-driven**

This is the largest edit. Replace the ENTIRE contents of `web/src/components/CacheTable.tsx` with:

```tsx
import { useMemo, useState } from "react";
import { Checkbox } from "./Checkbox";
import { RiskBadge } from "./RiskBadge";
import { ProviderIcon } from "./ProviderIcon";
import { humanBytes, staleness, RiskValue } from "@/lib/format";
import { COLUMNS, type ColumnDef, type SortKey } from "./CacheTable/columns";
import { useHiddenColumns } from "@/hooks/useHiddenColumns";

export interface CacheTableRow {
  id: string;
  provider: string;
  label: string;
  path: string;
  size_bytes: number;
  risk: RiskValue;
  mtime: number | null;
  recipeHint: string;
  owner: string | null;
  group: string | null;
  perms: string | null;
}

type SortDir = "asc" | "desc";

const RISK_RANK: Record<RiskValue, number> = {
  safe: 0,
  reclaimable: 1,
  dangerous: 2,
};

const DEFAULT_DIR: Record<SortKey, SortDir> = {
  provider: "asc",
  size: "desc",
  risk: "desc",
  stale: "desc",
};

function makeComparator(
  key: SortKey,
  dir: SortDir,
  now: number,
): (a: CacheTableRow, b: CacheTableRow) => number {
  const sign = dir === "asc" ? 1 : -1;
  return (a, b) => {
    switch (key) {
      case "size":
        return sign * (a.size_bytes - b.size_bytes);
      case "provider":
        return (
          sign * (a.provider.localeCompare(b.provider) || a.label.localeCompare(b.label))
        );
      case "risk":
        return (
          sign * (RISK_RANK[a.risk] - RISK_RANK[b.risk]) ||
          b.size_bytes - a.size_bytes
        );
      case "stale": {
        if (a.mtime === null && b.mtime === null) return 0;
        if (a.mtime === null) return 1;
        if (b.mtime === null) return -1;
        const ageA = now - a.mtime;
        const ageB = now - b.mtime;
        return sign * (ageA - ageB);
      }
    }
  };
}

export type CacheTableDensity = "sparse" | "dense";

export function CacheTable({
  rows,
  selected,
  onToggle,
  density = "sparse",
}: {
  rows: CacheTableRow[];
  selected: Set<string>;
  onToggle: (id: string, next: boolean) => void;
  density?: CacheTableDensity;
}) {
  const { isVisible } = useHiddenColumns();
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "size",
    dir: "desc",
  });

  const visibleColumns: ColumnDef[] = useMemo(
    () => COLUMNS.filter((c) => isVisible(c.id)),
    [isVisible],
  );

  const gridTemplate = useMemo(
    () => `28px ${visibleColumns.map((c) => c.width).join(" ")}`,
    [visibleColumns],
  );

  const sortedRows = useMemo(() => {
    const nowSecs = Date.now() / 1000;
    return [...rows].sort(makeComparator(sort.key, sort.dir, nowSecs));
  }, [rows, sort]);

  function headerClick(key: SortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: DEFAULT_DIR[key] },
    );
  }

  if (rows.length === 0) {
    return (
      <div className="p-8 text-center text-text-dim font-mono text-sm">
        (no entries)
      </div>
    );
  }

  return (
    <div className="font-mono text-[11px]">
      <div
        className="grid gap-3 px-4 py-2 border-b border-border"
        style={{ gridTemplateColumns: gridTemplate }}
      >
        <div />
        {visibleColumns.map((col) =>
          col.sortable ? (
            <SortHeader
              key={col.id}
              label={col.label}
              col={col.id as SortKey}
              align={col.align}
              sort={sort}
              onClick={headerClick}
            />
          ) : (
            <div
              key={col.id}
              className={`uppercase tracking-widest text-[9.5px] text-text-muted ${
                col.align === "right" ? "flex justify-end" : ""
              }`}
            >
              {col.label}
            </div>
          ),
        )}
      </div>
      {sortedRows.map((r) => {
        const isSelected = selected.has(r.id);
        const rowPad = density === "dense" ? "py-[3px]" : "py-[7px]";
        return (
          <div
            key={r.id}
            className={`grid gap-3 px-4 ${rowPad} items-center border-b border-border-subtle hover:bg-bg-elev-1`}
            style={{ gridTemplateColumns: gridTemplate }}
          >
            <Checkbox
              checked={isSelected}
              onChange={(next) => onToggle(r.id, next)}
              label={`select ${r.provider} ${r.label}`}
            />
            {visibleColumns.map((col) => (
              <Cell key={col.id} col={col} row={r} density={density} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function Cell({
  col,
  row,
  density,
}: {
  col: ColumnDef;
  row: CacheTableRow;
  density: CacheTableDensity;
}) {
  switch (col.id) {
    case "provider":
      return density === "dense" ? (
        <div className="flex items-baseline gap-1.5 min-w-0">
          <ProviderIcon
            slug={row.provider}
            size={14}
            className="shrink-0 self-center text-text-accent"
          />
          <span className="text-text-accent font-medium shrink-0">{row.provider}</span>
          <span
            className="text-text-muted text-[10px] truncate"
            title={row.path !== "—" ? row.path : row.label}
          >
            {row.label}
          </span>
        </div>
      ) : (
        <div className="min-w-0 flex items-center gap-1.5">
          <ProviderIcon
            slug={row.provider}
            size={14}
            className="shrink-0 text-text-accent"
          />
          <div className="min-w-0">
            <div className="text-text-accent font-medium truncate">{row.provider}</div>
            <div
              className="text-text-muted text-[9.5px] mt-px truncate"
              title={row.path !== "—" ? row.path : row.label}
            >
              {row.label}
            </div>
          </div>
        </div>
      );
    case "size":
      return (
        <div className="text-right tabular-nums font-medium">
          {humanBytes(row.size_bytes)}
        </div>
      );
    case "risk":
      return (
        <div>
          <RiskBadge risk={row.risk} />
        </div>
      );
    case "stale":
      return (
        <div className="text-right text-text-muted text-[10px] tabular-nums">
          {row.mtime === null ? "" : staleness(row.mtime)}
        </div>
      );
    case "owner":
      return (
        <div className="text-text-dim text-[10.5px] truncate">
          {row.owner ?? "—"}
        </div>
      );
    case "perms":
      return (
        <div className="text-text-dim text-[10px] font-mono tabular-nums">
          {row.perms ?? "—"}
        </div>
      );
  }
}

function SortHeader({
  label,
  col,
  align,
  sort,
  onClick,
}: {
  label: string;
  col: SortKey;
  align?: "right";
  sort: { key: SortKey; dir: SortDir };
  onClick: (col: SortKey) => void;
}) {
  const active = sort.key === col;
  const caret = active ? (sort.dir === "asc" ? "▴" : "▾") : "";
  const ariaSort: "ascending" | "descending" | "none" = active
    ? sort.dir === "asc"
      ? "ascending"
      : "descending"
    : "none";
  return (
    <button
      type="button"
      onClick={() => onClick(col)}
      aria-sort={ariaSort}
      className={`flex items-center gap-1 uppercase tracking-widest text-[9.5px] transition-colors cursor-pointer hover:text-text ${
        active ? "text-text" : "text-text-muted"
      } ${align === "right" ? "justify-end" : ""}`}
    >
      <span>{label}</span>
      <span className="w-2 text-[8px] leading-none text-risk-reclaim">{caret}</span>
    </button>
  );
}
```

- [ ] **Step 5: Wire `ColumnsPicker` into `Scan.tsx`**

Open `web/src/pages/Scan.tsx`. Find the filter-pill row (the `<div>` containing the all/safe/reclaim/danger filter buttons). Add `<ColumnsPicker />` to the right-hand side of that row, before the `scanned N min ago` text and the `rescan now` button.

Import at the top of the file:

```tsx
import { ColumnsPicker } from "@/components/ColumnsPicker";
```

Then in the JSX, modify the filter row. The existing shape is roughly:

```tsx
<div className="flex items-center gap-3 px-6 py-3">
  {/* filter pills here */}
  <span className="text-text-dim text-[11px]">scanned ...</span>
  <button onClick={...}>↻ rescan now</button>
</div>
```

Change it to:

```tsx
<div className="flex items-center gap-3 px-6 py-3">
  {/* filter pills here — unchanged */}
  <div className="flex-1" />
  <ColumnsPicker />
  <span className="text-text-dim text-[11px]">scanned ...</span>
  <button onClick={...}>↻ rescan now</button>
</div>
```

The exact existing layout may differ slightly; keep all existing children in place and only add the spacer `<div className="flex-1" />` (if missing) + `<ColumnsPicker />` in the right place. Match the style of sibling elements.

- [ ] **Step 6: Regenerate TypeScript types (optional)**

If a backend is running locally:

```bash
cd <worktree>/web
npm run gen:types
```

Expected: `src/api/types.gen.ts` updated with the new `uid`, `gid`, `mode`, `owner`, `group`, `perms` fields on the entry shape. If the backend isn't running, skip this step — `useScan.ts` uses a locally-defined mapping, not the generated type directly, so tests still pass.

- [ ] **Step 7: Run the full test suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 106 tests (103 prior + 3 new CacheTable tests). The 7 existing CacheTable tests should continue to pass because the fixture updates kept their rows valid and the visible behavior (sorting, selection, empty state) is unchanged.

- [ ] **Step 8: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd <worktree>
git add web/src/components/CacheTable.tsx web/src/hooks/useScan.ts web/src/pages/Scan.tsx web/tests/unit/CacheTable.test.tsx web/src/api/types.gen.ts
git commit -m "feat(web): CacheTable registry-driven rendering + owner/perms cells + picker wiring

Grid template and cell rendering now read from COLUMNS. useHiddenColumns
filters which columns render. Two new cells (OwnerCell, PermsCell) show
row.owner and row.perms with — fallback. ColumnsPicker plugged into the
Scan page filter-pill row."
```

(Include `web/src/api/types.gen.ts` in `git add` only if Step 6 regenerated it.)

---

## Task 8: Build + visual verification

**Files:** none (read-only task)

- [ ] **Step 1: Production build**

Run:
```bash
cd <worktree>/web
npm run build
```

Expected: clean build. Bundle delta ~2 KB gzipped (picker + registry + hook).

- [ ] **Step 2: Full frontend test sweep**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 106 tests.

- [ ] **Step 3: Full backend test sweep**

Run:
```bash
cd <worktree>
uv run pytest 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 4: Dev-server visual check**

Run:
```bash
cd <worktree>/web
npm run dev
```

And in another terminal, start the backend so the Scan page can fetch data:

```bash
cd <worktree>
uv run diskdoctor serve --port 8731 --no-browser
```

In the browser:

1. **Scan page loads** — two new columns (`owner`, `perms`) are visible alongside the existing five. Real entries show real values; ollama/docker-style entries show `—` in both.
2. **Click `columns ▾`** in the toolbar — dropdown appears with six checkboxes. `provider` is disabled (shown as locked).
3. **Uncheck `stale`** — the stale column disappears immediately. Reload the page → stale is still hidden.
4. **Uncheck `owner` and `perms`** — the table returns to the pre-feature 5-column layout.
5. **Click outside the dropdown** — it closes.
6. **Open the dropdown, press Escape** — it closes; focus returns to the `columns ▾` button.
7. **Sort works** — click `size` / `risk` / `stale` headers → rows reorder; `owner` and `perms` headers are plain text, not clickable (non-sortable).
8. **Cleanup wizard** — pick an entry with a real owner, run the wizard. Review step still renders; owner/perms are not shown there (scope intentionally excluded), but nothing is broken.
9. **Narrow viewport** — at <768px the sidebar force-collapses (existing behavior); the table with all seven columns may overflow horizontally. Use the picker to hide columns as needed.
10. **Reset to defaults** — Settings → `↺ reset to defaults` restores all columns visible.

- [ ] **Step 5: Confirm no regressions**

Spot-check:
- Provider icons still render in the provider cell.
- Disk-usage bar refreshes after scans/snapshots/cleanups.
- Sidebar drag-resize still works.
- Theme toggle still works.
- OS detection gate still renders on non-supported UA.

- [ ] **Step 6: Final commit (only if any visual touch-ups happened)**

If nothing changed in this task beyond verification, skip. Otherwise stage and commit.

---

## Out of scope

- Drag-to-reorder columns.
- Column-width dragging.
- Picker on DiffTable, Providers config, or wizard tables.
- Group column surfaced in the UI (field is in the API for future use).
- Per-route column-visibility state (single global key).
- Server-side caching of pwd/grp lookups beyond the `lru_cache` process-level cache.

## Rollback

Eight commits, each self-contained. Reverse-order revert rolls back cleanly:

```bash
cd <worktree>
git log --oneline main..HEAD
# git revert each SHA in reverse order
```

`Report.from_json` uses `.get()` for the new entry keys, so old snapshots (pre-feature) and snapshots written by this feature (post-revert) both keep deserializing without error. No data migration.
