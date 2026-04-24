# Provider details — design

**Date:** 2026-04-24
**Status:** approved, ready for implementation plan

## 1. Goal

Let users drill into a provider from the Providers page to see **where it scans**, **what its cleanup recipe does**, and **what its last scan found**, without leaving the page or navigating to a separate route.

Today the Providers table shows name, description, platforms, risk, available flag, enabled toggle, and a usage bar. None of that answers "what paths does the ollama provider actually check on my machine?" or "what shell commands would a cleanup run?". This design exposes both.

## 2. User experience

Each row on the Providers page gets a leading chevron. Clicking the chevron (or pressing Enter/Space while it has focus) expands an inline panel **below the row**, inside the same grid, spanning the full row width.

- Multiple rows can be expanded at once.
- Expansion state is not persisted — closing the browser resets everything to collapsed.
- The panel is keyboard-reachable and announces `aria-expanded` on the chevron and a descriptive label on the panel region.

The panel has up to three sections, stacked vertically:

1. **Paths** — where the provider looks.
2. **Cleanup recipe** — the shell commands a cleanup would run.
3. **Last scan** — totals and timing from the most recent auto-snapshot.

Sections render based on what's available (see §5).

## 3. Non-goals

- No per-provider "Test now" or "Run cleanup" button from the details panel. Cleanup still runs from the Scan page / API.
- No YAML editing from the UI.
- No persistence of expansion state across reloads or pages.
- No deep-link (`/providers#ollama-cache`).
- No `details` prose for YAML-backed providers — their paths list is self-explanatory, and the YAML is the source of truth.
- No separate route (`/providers/:name`).

## 4. Backend

### 4.1 Class-level metadata

Add a single new class variable on `Provider` (base):

```python
# src/diskdoctor/providers/base.py
class Provider(ABC):
    ...
    details: ClassVar[str | None] = None
```

`details` is an optional short prose string (1–3 sentences, plain text) that explains what a **class provider** scans. YAML providers leave it `None` — their `raw_paths` already documents the scan.

Override `details` on all six class providers with a concrete, user-facing description:

- `OllamaProvider` — what `ollama` stores under `~/.ollama/models` and why it can be large.
- `DockerProvider` — what `docker system df` / `docker builder prune` reclaims.
- `HuggingFaceProvider` — the HF hub cache layout.
- `LargeFilesProvider` — the heuristic: top-N files over threshold under the home directory.
- `LmStudioProvider` — where LM Studio keeps its downloaded models.
- `VenvProvider` — which directories it treats as disposable virtualenvs.

Exact wording is an implementation-time choice; the plan must specify the content. Reviewers check that each string is ≤300 characters and doesn't duplicate `description`.

### 4.2 Promote private path attributes on `PathProvider`

Rename:

- `PathProvider._raw_paths` → `PathProvider.raw_paths`
- `PathProvider._recipe_template` → `PathProvider.recipe_template`

Update all internal references (`discover()`, `from_yaml()`, tests). These are new public attributes on `PathProvider` only — class providers don't have them.

### 4.3 Extract `resolve_paths()` helper

Today `PathProvider.discover()` does path expansion, globbing, and existence checking inline. Extract the **resolution step only** (expand → glob → filter to existing) into a reusable method:

```python
def resolve_paths(self) -> list[pathlib.Path]:
    """Expand ~, $VARS and globs in raw_paths, return paths that exist."""
```

`discover()` then calls `resolve_paths()` and keeps its sizing / recipe / Entry construction logic. No behavior change; pure refactor for DRY.

The API layer uses `resolve_paths()` directly to populate `resolved_paths` in the response (see §4.4).

### 4.4 Extend `/api/providers`

`ProviderInfo` (in `diskdoctor/web/models.py`) grows four optional fields:

```python
class ProviderInfo(BaseModel):
    # existing fields
    name: str
    description: str
    risk: str
    platforms: list[str]
    available: bool
    required_binary: str | None
    kind: Literal["class", "yaml"]
    reason_if_unavailable: str | None = None

    # new (all optional — populated per provider kind)
    details: str | None = None           # class providers that set it
    raw_paths: list[str] | None = None   # yaml providers only
    resolved_paths: list[str] | None = None  # yaml providers only
    recipe_template: list[str] | None = None # yaml providers only
```

`GET /api/providers` populates them as follows:

- For class providers: `details` from the class var; the three YAML-only fields stay `None`.
- For YAML providers: `raw_paths` from `provider.raw_paths`, `recipe_template` from `provider.recipe_template`, `resolved_paths` by calling `provider.resolve_paths()` and mapping to strings. `details` stays `None`.

This keeps everything behind the existing endpoint — the frontend doesn't need a second round-trip to open a panel. Payload stays well under 100 KB for a realistic provider set (~25 providers × ~2 KB each).

`resolve_paths()` does filesystem I/O. The existing `/api/providers` already calls `p.available()` which can touch disk too, so this is consistent. Providers resolve all paths once per request — if this ever shows up in a profile, we add caching; not before.

### 4.5 No new endpoint for last-scan stats

Last-scan stats come from the existing `/api/snapshots?kind=auto&limit=1` endpoint. The frontend fetches the newest auto snapshot once and joins its `per_provider` array against the providers list by `name`. This avoids duplicating telemetry in two places and keeps the providers endpoint side-effect-free of scan state.

## 5. Frontend

### 5.1 Providers page layout change

The Providers page currently renders a 7-column grid. Add a **leading 24px chevron column** before the existing toggle column. Row layout becomes:

```
[chevron] [icon] [name/description] [platforms] [risk] [available] [size] [toggle]
```

The chevron is a button with `aria-expanded={isExpanded}` and an `aria-label` that flips between "Show details for {name}" and "Hide details for {name}". Clicking it (or Enter/Space) toggles that row's entry in a `Set<string>` stored in `useState` on the page component.

### 5.2 Expanded panel

When a row is expanded, a **new grid row** is rendered immediately after it with `gridColumn: "1 / -1"` so it spans the full width. The panel's content is `<ProviderDetailsPanel>`, a new component in `web/src/components/ProviderDetailsPanel.tsx`.

`<ProviderDetailsPanel>` props:

```ts
interface Props {
  provider: ProviderInfo;           // from /api/providers
  lastAuto: ProviderTimingMeta | null; // pre-joined by the Providers page
}
```

### 5.3 Panel sections

**Paths**

- If `provider.raw_paths` is populated (YAML provider): render a two-column listing — raw path on the left (monospace, muted), resolved path(s) on the right. If `resolved_paths` is empty for a given raw path, show "(no match)" in muted text. If a glob expanded to multiple paths, list them all under the same raw-path row.
- If `provider.details` is populated (class provider): render it as a single `<p>` block in the paths section's place.
- If neither is set (shouldn't happen, but defensive): render "No path information available." muted.

**Cleanup recipe**

- Only shown for YAML providers (i.e. when `recipe_template` is non-null).
- Rendered as a `<pre><code>` block with each line of `recipe_template` on its own line. `{path}` is left literal — it's a template, not a concrete command.
- A short caption above reads "Runs once per matched path, with `{path}` replaced by the resolved path."

**Last scan**

- Shown for every provider where `lastAuto` is non-null.
- Three inline stats: `entries: N`, `total: <formatted bytes>`, `duration: <formatMs>`.
- If `lastAuto` is null (no auto snapshots yet), the section is simply omitted — no empty placeholder.

### 5.4 Data hook

Add `useLatestAutoSnapshot()` in `web/src/hooks/useSnapshots.ts` (extend existing file):

```ts
export function useLatestAutoSnapshot(): UseQueryResult<SnapshotMeta | null>
```

Fetches `/api/snapshots?kind=auto&limit=1`, returns the single meta or `null` if the list is empty. Reuses the same TanStack Query key pattern as existing snapshot queries.

The Providers page calls this hook once and builds a `Map<string, ProviderTimingMeta>` keyed on provider name. Each expanded panel reads from the map — no per-panel fetch.

### 5.5 Accessibility

- Chevron is a `<button>` (not a div), so it's reachable by tab and actionable by Enter/Space natively.
- `aria-expanded` reflects the row's state.
- The expanded panel uses `role="region"` with `aria-label="{provider.name} details"`.
- No focus trap. Collapsing a row doesn't move focus back to the chevron automatically; the default tab order after collapse lands on the next row's controls, which is fine.
- Chevron icon rotates 90° on expand via a Tailwind transition — purely visual, has `aria-hidden="true"` on the SVG.

### 5.6 Styling

- Panel background: `bg-surface-muted` (one step darker than row background) to visually nest it under its owner row.
- Padding: `px-4 py-3`.
- Section headings: small uppercase (`text-xs uppercase tracking-wide text-text-dim`).
- Code blocks: existing `bg-surface-sunken font-mono` pattern used elsewhere.

## 6. Testing

### 6.1 Python

- `tests/test_path_provider.py` — new test file:
  - `test_resolve_paths_expands_tilde_and_vars`
  - `test_resolve_paths_expands_globs`
  - `test_resolve_paths_filters_nonexistent`
  - `test_discover_uses_resolve_paths_output` (sanity: no behavior change on existing providers)

- `tests/web/test_routes_providers.py` — new file (currently no dedicated tests for the `/api/providers` endpoint):
  - `test_api_providers_yaml_populates_paths_and_recipe`
  - `test_api_providers_class_populates_details_not_paths`
  - `test_api_providers_resolved_paths_only_includes_existing`

### 6.2 TypeScript

- `web/src/components/ProviderDetailsPanel.test.tsx` — new:
  - renders details prose for class provider
  - renders raw/resolved path grid for YAML provider
  - renders recipe template verbatim with `{path}` literal preserved
  - omits last-scan section when `lastAuto` is null
- `web/src/pages/Providers.test.tsx` — extend:
  - chevron click toggles row expansion
  - two rows can be expanded simultaneously
  - `aria-expanded` reflects state
  - collapsed rows don't render `<ProviderDetailsPanel>` in the DOM

## 7. File structure

**New:**
- `web/src/components/ProviderDetailsPanel.tsx`
- `web/src/components/ProviderDetailsPanel.test.tsx`
- `tests/test_path_provider.py`

**Modified:**
- `src/diskdoctor/providers/base.py` — `details` ClassVar, rename private attrs, add `resolve_paths()`
- `src/diskdoctor/providers/{docker,huggingface,large_files,lm_studio,ollama,venv}.py` — populate `details` ClassVar
- `src/diskdoctor/web/models.py` — four new optional fields on `ProviderInfo`
- `src/diskdoctor/web/routes_scan.py` — populate new fields in `/api/providers`
- `web/src/api/types.ts` (or wherever `ProviderInfo` lives TS-side) — mirror new fields
- `web/src/hooks/useSnapshots.ts` — add `useLatestAutoSnapshot()`
- `web/src/pages/Providers.tsx` — chevron column, expansion state, render panel
- `web/src/pages/Providers.test.tsx` — new tests
- `tests/web/test_routes_providers.py` (new file)

## 8. Schema / backward compatibility

- `/api/providers` response grows optional fields — existing clients ignore them.
- `PathProvider.raw_paths` / `recipe_template` are renames of private attrs; no external consumers.
- No snapshot schema change.

## 9. Risks / trade-offs

- **Resolving paths on every `/api/providers` call** adds filesystem I/O. Mitigation: call already exists (`available()` touches disk). If it becomes a hotspot, cache per-request. Not caching prematurely.
- **`details` ClassVar is free-form prose** — no enforcement that it stays up to date with the code. Acceptable: it's small, visible, and reviewers can catch drift.
- **Expansion state lost on navigation** — fine for v1; if users ask, we add to `useSettings` later.
- **Panel spans full row width via `gridColumn: 1 / -1`** — depends on the Providers page staying a CSS grid. If it ever refactors to a table, the panel needs to become a full-width `<tr><td colspan=N>`. Plan should note this.
