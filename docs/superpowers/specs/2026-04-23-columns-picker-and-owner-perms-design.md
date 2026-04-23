# Column picker + owner/perms columns — design

Date: 2026-04-23
Status: approved for implementation plan

## Goal

Two coupled additions to the Scan page:

1. **Column picker** — a `columns ▾` dropdown in the Scan page toolbar that lets the user hide or show each column of `CacheTable`. State persists in `Settings`.
2. **Owner and perms columns** — two new columns fed by stat data gathered server-side during provider discovery. `owner` shows the user's login name (e.g. `shamil`); `perms` shows `drwxr-xr-x` rendered by `stat.filemode`. Entries without a filesystem path (e.g. ollama models, docker images) show `—`.

The two features land together because adding new columns without the picker would over-crowd the table, and the picker needs at least one new column to justify shipping. The column registry introduced here is the infrastructure any future column addition plugs into without rework.

## Scope

- CacheTable only. No picker on DiffTable, Providers config, or the cleanup-wizard tables.
- Visibility only — no drag-reorder. Column order is fixed by `COLUMNS` declaration order.
- Both new columns visible by default.
- `provider` column is non-hideable (row identifier). Every other column is hideable.
- Backend: extend the `Entry` dataclass and serialization. No snapshot schema bump (additive fields).
- Frontend: new column registry, new hook, new picker component, updated `CacheTable`.

## Backend

### `Entry` dataclass

`src/diskdoctor/types.py`:

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
    # NEW — populated when the entry is backed by a real filesystem path.
    # None for class-based providers whose entries are logical identifiers
    # (ollama models, docker images).
    uid: int | None = None
    gid: int | None = None
    mode: int | None = None
    owner: str | None = None  # login name from pwd.getpwuid
    group: str | None = None  # group name from grp.getgrgid
    perms: str | None = None  # stat.filemode(mode) e.g. "drwxr-xr-x"
```

All six new fields default to `None`. Frozen dataclass semantics preserved.

### `sizer` helper

Add a narrow companion to `size_path`:

```python
# src/diskdoctor/sizer.py
import pwd
import grp
import stat as stat_mod
from functools import lru_cache
from pathlib import Path

@dataclass(frozen=True)
class StatFields:
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
    """Return uid/gid/mode + resolved owner/group/perms for `path`, or None on
    permission/missing errors. Uses lstat so symlinks report their own
    ownership, not the target's — matches how size_path handles symlinks.
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
```

The `lru_cache` on name lookups is per-process and bounded — cache-line churn during a scan of 500+ entries costs ~5 `getpwuid` calls instead of 500+.

### Provider integration

`PathProvider` (in `providers/base.py`) calls `stat_fields(resolved_path)` once per resolved path when constructing each `Entry`. On `None` return, all six fields are left as `None` (defaults).

Class-based providers (`ollama`, `docker`, etc.) whose entries are logical identifiers construct `Entry` without the new fields (same as today; defaults kick in).

For class-based providers that DO resolve to a real path (e.g. `huggingface-hub` emits Entry with `path=...`), they call `stat_fields` the same way `PathProvider` does.

### Serialization

`Report.to_json()` already uses dataclass_dict-style serialization. The new fields are additive — old readers ignoring unknown fields is already documented as the contract. No `SNAPSHOT_SCHEMA_VERSION` bump.

### API response

`/api/scan` returns Entry objects with the new fields. Example:

```json
{
  "id": "firefox-cache-0",
  "provider": "firefox-cache",
  "path": "/Users/shamil/Library/Caches/Firefox",
  "label": "/Users/shamil/Library/Caches/Firefox",
  "size_bytes": 2500000000,
  "mtime": 1780000000.0,
  "risk": "safe",
  "recipe": ["rm -rf /Users/shamil/Library/Caches/Firefox"],
  "uid": 501,
  "gid": 20,
  "mode": 16877,
  "owner": "shamil",
  "group": "staff",
  "perms": "drwxr-xr-x"
}
```

TypeScript types regenerate via the existing `npm run gen:types` script.

## Frontend

### Column registry

New module `web/src/components/CacheTable/columns.ts`:

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
  width: string;              // CSS grid track (e.g. "1fr", "90px")
  sortable: boolean;
  align?: "right";
  hideable: boolean;          // false for provider (row identifier)
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

export type SortKey = Extract<ColumnId, "provider" | "size" | "risk" | "stale">;
```

### Persistence

One new field on `Settings`:

```ts
interface Settings {
  // ... existing fields
  scanTableHiddenColumns: ColumnId[];  // default: []
}
```

Follows the `useSelectedProviders` pattern (store the hidden set, not the visible set), so future additions to `COLUMNS` default visible.

`read()` in `useSettings.ts` validates array members against the known `ColumnId` union; unknown values are dropped silently.

`DEFAULTS.scanTableHiddenColumns = []`.

`reset()` restores to `[]`.

### Hook

New `web/src/hooks/useHiddenColumns.ts`:

```ts
export interface UseHiddenColumnsResult {
  hiddenColumns: ReadonlySet<ColumnId>;
  isVisible: (id: ColumnId) => boolean;
  setHidden: (id: ColumnId, hidden: boolean) => void;
}

export function useHiddenColumns(): UseHiddenColumnsResult {
  const { settings, update } = useSettings();
  const hiddenColumns = new Set(settings.scanTableHiddenColumns);
  const isVisible = (id: ColumnId) => !hiddenColumns.has(id);
  const setHidden = useCallback((id: ColumnId, hidden: boolean) => {
    const next = new Set(settings.scanTableHiddenColumns);
    if (hidden) next.add(id);
    else next.delete(id);
    update({ scanTableHiddenColumns: [...next] });
  }, [settings.scanTableHiddenColumns, update]);
  return { hiddenColumns, isVisible, setHidden };
}
```

Non-hideable columns (`provider`) are always visible regardless of the hidden set — `isVisible("provider")` returns `true` even if someone hand-edits localStorage to include `"provider"`.

### `CacheTable` rewrite for registry-driven rendering

Current `CacheTable` hardcodes the grid template and header. Replace with:

```tsx
const visibleColumns = COLUMNS.filter(
  (c) => !c.hideable || isVisible(c.id),
);

const gridTemplate = `28px ${visibleColumns.map((c) => c.width).join(" ")}`;

// Header
<div className="grid" style={{ gridTemplateColumns: gridTemplate }}>
  <div /> {/* checkbox column */}
  {visibleColumns.map((col) => (
    col.sortable
      ? <SortHeader key={col.id} label={col.label} col={col.id as SortKey} align={col.align} sort={sort} onClick={headerClick} />
      : <div key={col.id} className={`uppercase tracking-widest text-[9.5px] text-text-muted ${col.align === "right" ? "justify-end flex" : ""}`}>{col.label}</div>
  ))}
</div>

// Row — rendered cells driven by visibleColumns
{sortedRows.map((r) => (
  <Row key={r.id} row={r} visibleColumns={visibleColumns} ... />
))}
```

The row component has a switch on `col.id` that maps each column to its cell renderer. Keeps the existing dense/sparse logic for the `provider` column intact (that's still the only column with `ProviderIcon` + two-line label in sparse mode).

### Columns picker component

New `web/src/components/ColumnsPicker.tsx`:

- Button: `columns ▾` styled like existing filter pills (same border, text-[11px], same hover state).
- Click opens a floating panel anchored below-right of the button (absolute positioning; no portal).
- Panel contents:
  ```
  show columns
  ┌────────────────────┐
  │ ☑ provider (locked)│   ← disabled checkbox, can't be hidden
  │ ☑ size             │
  │ ☑ risk             │
  │ ☑ stale            │
  │ ☑ owner            │
  │ ☑ perms            │
  └────────────────────┘
  ```
- Each row is a `role="menuitemcheckbox"` with `aria-checked`. Click toggles via `setHidden`.
- Keyboard: `Tab` cycles items; `Space`/`Enter` toggles; `Escape` closes and returns focus to the button; `ArrowDown`/`ArrowUp` move focus within the menu.
- Click-outside closes (via a one-shot window `mousedown` listener while open).
- Button has `aria-haspopup="menu"`, `aria-expanded={open}`, `aria-controls` pointing at the panel id.
- Panel has `role="menu"`, `aria-label="Toggle columns"`.

### Scan page integration

`web/src/pages/Scan.tsx` renders the picker in the toolbar row with the filter pills:

```tsx
<div className="flex items-center gap-3 px-6 py-3">
  <FilterPills ... />
  <div className="flex-1" />
  <ColumnsPicker />
  <span className="text-text-dim text-[11px]">scanned {ago} ago</span>
  <button onClick={rescan}>↻ rescan now</button>
</div>
```

### Rendering owner / perms cells

```tsx
function OwnerCell({ row }: { row: CacheTableRow }) {
  return (
    <div className="text-text-dim text-[10.5px] truncate">
      {row.owner ?? "—"}
    </div>
  );
}

function PermsCell({ row }: { row: CacheTableRow }) {
  return (
    <div className="text-text-dim text-[10px] font-mono tabular-nums">
      {row.perms ?? "—"}
    </div>
  );
}
```

`CacheTableRow` gains three optional fields on the frontend too: `owner?: string | null`, `group?: string | null`, `perms?: string | null`. The `useScan` hook passes them through from the API response.

## Accessibility

- Picker button: `aria-haspopup`, `aria-expanded`, `aria-controls`.
- Picker panel: `role="menu"`, `aria-label`.
- Items: `role="menuitemcheckbox"`, `aria-checked`.
- Disabled item (`provider`): `aria-disabled="true"`, checkbox input `disabled`.
- Focus restoration: closing the panel returns focus to the button.
- Arrow-key navigation within the panel, Escape to close — standard menu semantics.

## Edge cases

- **Entries without a path** → owner, group, perms all null → cells show `—`.
- **Permission-denied stat** → `stat_fields` returns None → cells show `—`.
- **Symlinks** → `lstat` used (symlink's own metadata), matching `size_path`'s behavior.
- **pwd/grp lookup failures** (orphaned UID/GID) → `_owner_name` falls back to `str(uid)`; the cell shows `"501"` rather than `—` since we do have the numeric info.
- **Old snapshots missing the new fields** → deserialize with defaults → cells show `—`. No migration needed.
- **User hand-edits localStorage to include an unknown column id** → validated-out on read → no crash.

## Testing

### Backend

- `tests/test_sizer.py` (new test in existing file): `stat_fields(tmpdir)` returns non-None with matching `st_uid`, `st_gid`, `st_mode`, correct `owner`/`group`/`perms`. `stat_fields(non_existent_path)` returns None. `stat_fields` on a symlink returns the symlink's metadata, not the target's.
- `tests/test_providers.py` (extend existing provider tests): a `PathProvider` backed by a tempdir emits entries with `uid`, `gid`, `mode`, `owner`, `group`, `perms` populated. A class-based provider (`OllamaProvider` with mock shell) emits entries with those fields all `None`.
- `tests/test_snapshot_serialization.py` (new or extend): `Entry` → JSON → `Entry` round-trips the new fields. An old snapshot JSON without the new fields deserializes with them as `None`.

### Frontend

- `web/tests/unit/columns.test.ts` (new): `COLUMNS` is exhaustive (every `ColumnId` has a matching entry); `provider` is the only non-hideable column; no duplicate ids.
- `web/tests/unit/useHiddenColumns.test.ts` (new): default is `isVisible` true for all; `setHidden("stale", true)` persists to localStorage; `setHidden("stale", false)` removes it; `isVisible("provider")` is `true` even if `"provider"` is in the hidden set (safety).
- `web/tests/unit/ColumnsPicker.test.tsx` (new): renders 6 checkboxes; `provider` checkbox is disabled; clicking a checkbox calls `setHidden`; `Escape` closes; click-outside closes; `aria-expanded` flips.
- `web/tests/unit/CacheTable.test.tsx` (extend):
  - With `stale` hidden, the stale column's header and cells are absent from the DOM.
  - With `owner` visible and row data providing `owner: "shamil"`, the cell shows `shamil`.
  - With `owner` visible and row data providing `owner: null`, the cell shows `—`.
  - Grid template reflects visible columns in order.

No new e2e tests — all behavior is unit-testable.

## Bundle and performance

- Backend: `lru_cache` on `_owner_name` / `_group_name` bounds the getpwuid/getgrgid syscalls to roughly the distinct UID/GID count on the host (typically 1-5 per scan).
- Frontend: one new component + one new hook + one new module. Bundle delta ~2 KB gzipped.
- API response grows by ~40 bytes per entry for the extra fields. At 500 entries per scan that's ~20 KB uncompressed; negligible compressed.

## Non-goals

- No drag-to-reorder columns.
- No column-resizing by dragging borders.
- No picker on DiffTable, Providers config, or wizard tables.
- No per-route column state (single `scanTableHiddenColumns` key only).
- No group column in the UI (data is in the API for future use).
- No "recommended columns" preset or column groups.
- No cross-request cache for pwd/grp lookups beyond the `lru_cache` process-level cache.
- No column width override by user — widths are fixed in `COLUMNS`.
- No export that includes/excludes columns based on visibility — visibility is UI-only.

## Test-count expectations

Starting at 87 (post OS-detection merge):
- Backend: ~8 new Python tests
- Frontend: ~10 new Vitest tests

Final ≈ 105 total.

## Open questions resolved during brainstorming

- **Which columns get added** (Q1): owner + perms. No group column in the UI.
- **Which tables get the picker** (Q2): CacheTable only.
- **Picker placement** (Q3): toolbar dropdown in Scan page's filter row.
- **Default visibility of new columns** (Q4a): both visible by default.
- **Visibility vs. reordering** (Q4b): visibility only; no drag-reorder.
