# Collapsible sidebar — design

Date: 2026-04-22
Status: approved for implementation plan

## Goal

Let the user collapse the left sidebar to an icons-only strip so tables and pages get more horizontal room. Collapse state is sticky, lives in settings, and is forced on narrow viewports.

## User-visible behaviour

- A chevron button inside the sidebar header toggles between **expanded** (current 180px with glyph + label) and **collapsed** (48px, glyph only, with native tooltip on hover).
- `Cmd/Ctrl+B` triggers the same toggle — except when focus is in an editable element, where the browser's own bold-text shortcut wins.
- Setting persists to localStorage (part of the existing `diskdoctor.settings.v1` schema). Every toggle writes the setting; reloads preserve it. The Settings page exposes the same value via a `[ expanded ] [ collapsed ]` chip pair.
- Viewports below 768px (Tailwind `md`) **force** the collapsed layout regardless of the stored setting. In this mode the chevron is hidden and `Cmd/Ctrl+B` becomes a no-op. Resizing back above 768px restores the user's setting.

Default on first load: expanded.

## State model

One new field on `Settings`:

```ts
interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
  sidebarCollapsed: boolean; // NEW — default false
}
```

`DEFAULTS.sidebarCollapsed = false`. The existing `read()` in `useSettings.ts` already falls back to `DEFAULTS` for missing fields, so no migration is needed.

`reset()` sets it back to `false`.

## New hook: `useSidebarCollapsed`

```ts
export function useSidebarCollapsed(): {
  collapsed: boolean;            // effective state — honours the viewport override
  toggle: () => void;            // no-op when forceCollapsedByViewport
  forceCollapsedByViewport: boolean;
};
```

Internals:

- Reads `settings.sidebarCollapsed` from `useSettings`.
- Subscribes to `matchMedia("(max-width: 767px)")` — updates `forceCollapsedByViewport` live.
- `collapsed = forceCollapsedByViewport || settings.sidebarCollapsed`.
- `toggle()` flips `settings.sidebarCollapsed` via `useSettings().update`, but early-returns when `forceCollapsedByViewport` is true.

This hook is the single source of truth for layout and chrome. `AppShell`, `Sidebar`, and any keyboard handler all consume it.

## Layout changes (`AppShell.tsx`)

Grid template becomes derived:

```tsx
const { collapsed } = useSidebarCollapsed();
return (
  <div className={`min-h-screen grid ${collapsed ? "grid-cols-[48px_1fr]" : "grid-cols-[180px_1fr]"} bg-bg text-text font-sans`}>
    <Sidebar />
    <main className="flex flex-col min-w-0"><Outlet /></main>
  </div>
);
```

No animated transition on the grid template — one-frame snap. Avoids mid-resize layout thrash inside `<main>` (tables, sticky headers).

`AppShell` also installs a global keydown listener for `Cmd+B` on macOS, `Ctrl+B` on all other platforms — detected via `event.metaKey` when `navigator.platform` starts with `"Mac"`, otherwise `event.ctrlKey`. Matches VSCode/Linear/Slack convention. Handler:

- Calls `toggle()` from `useSidebarCollapsed`.
- Calls `e.preventDefault()` so the browser doesn't also bold-format the focused field on macOS.
- Short-circuits if `document.activeElement` is an `<input>`, `<textarea>`, or `[contenteditable="true"]` — editable surfaces keep their native behaviour.
- Short-circuits if `forceCollapsedByViewport` is true.

## Sidebar restructure (`Sidebar.tsx`)

### Nav-item structure refactor

Today each `Item` takes a single `label` string like `"◆ scan"`. Split into two props:

```tsx
function Item({ to, glyph, label, count }: {
  to: string;
  glyph: string;      // "◆"
  label: string;      // "scan"
  count?: number;
}) { ... }
```

Invocation:

```tsx
<Item to="/"          glyph="◆" label="scan" />
<Item to="/snapshots" glyph="⏱" label="snapshots" />
<Item to="/history"   glyph="≡" label="history" />
<Item to="/providers" glyph="⚙" label="providers" />
<Item to="/settings"  glyph="⚡" label="settings" />
```

### Rendering per mode

- **Expanded:** `[glyph] [label]` left-aligned, exactly as today (visually identical — we're just splitting the string).
- **Collapsed:** `[glyph]` centered. Label stays in the DOM as `<span className="sr-only">` so screen readers still announce `"scan"`; a `title={label}` on the link produces the hover tooltip.
- Glyph is `aria-hidden="true"` in both modes (decorative).
- `count` renders only when expanded. Dropped silently in collapsed mode.
- Active route: same background-fill as today (`bg-bg-elev-2 text-text`). Works at both widths — no special "active bar" indicator needed for collapsed mode.

### Header + chevron

- **Expanded:** `[colored dot] diskdoctor [◀]`. Chevron is right-aligned inside the existing brand row.
- **Collapsed:** only the colored dot, centered. The chevron `▶` sits in a thin row below the brand dot, also centered.
- **Force-collapsed:** chevron element is absent entirely; `useSidebarCollapsed` exposes `forceCollapsedByViewport` so `Sidebar` can skip rendering it.

Chevron button attributes:

- `aria-label` — `"Collapse sidebar"` when expanded, `"Expand sidebar"` when collapsed.
- `aria-expanded={!collapsed}`.
- Styled consistent with the existing buttons in the app (border, hover state).

### Workspace section header

The `workspace` small-caps label above the nav list hides when collapsed — it's scaffolding that adds noise in a 48px column.

## Settings page entry (`Settings.tsx`)

New `Section` between "Appearance" and "Minimum size cutoff":

```tsx
<Section
  title="Sidebar"
  description="Collapse the sidebar to icons only. Narrow viewports (below 768px) always collapse, regardless of this setting."
>
  <div className="flex gap-2">
    <Chip active={!settings.sidebarCollapsed} onClick={() => applyAndFlash({ sidebarCollapsed: false })}>
      expanded
    </Chip>
    <Chip active={settings.sidebarCollapsed} onClick={() => applyAndFlash({ sidebarCollapsed: true })}>
      collapsed
    </Chip>
  </div>
</Section>
```

The existing saved-flash mechanism handles feedback. No separate handler needed beyond `applyAndFlash`.

## Accessibility

- Chevron button: dynamic `aria-label`, `aria-expanded`.
- Nav items: glyph is `aria-hidden="true"`; label text always present in the DOM (visually hidden in collapsed mode via `sr-only`, not removed). `NavLink` still produces `aria-current="page"` for the active route.
- Tooltip: `title` attribute. Native, OS-styled, zero JS. Good enough for what is effectively supplementary text.
- Keyboard shortcut respects editable-surface focus; never hijacks text formatting in inputs.
- No focus-trap or focus-move on toggle — the chevron button retains focus, user continues their flow.

## Testing

- **`web/tests/unit/Sidebar.test.tsx` (new):**
  - Renders all 5 nav items with full labels when expanded.
  - In collapsed mode, each item's label text has class `sr-only` and the `<a>` carries the expected `title`.
  - Chevron button exists with the correct `aria-label` and `aria-expanded` per state.
  - Chevron is not rendered when `forceCollapsedByViewport` is true.
- **`web/tests/unit/useSidebarCollapsed.test.ts` (new):**
  - Default `collapsed` is `false` when settings default is false and matchMedia does not match.
  - `toggle()` flips `settings.sidebarCollapsed` in localStorage.
  - `matchMedia("(max-width: 767px)")` matching makes `collapsed` true even when `settings.sidebarCollapsed` is false.
  - Dispatching a matchMedia change event updates `collapsed` live.
  - `toggle()` is a no-op when `forceCollapsedByViewport` is true (settings value does not change).
- **Existing tests:** no changes. Sidebar rendering isn't asserted in any existing test.
- **No e2e.** All viewport-forcing behaviour is unit-testable with `matchMedia` mocking.

## Bundle and performance

- No new dependencies. `matchMedia` is a platform API.
- One tiny module added (`useSidebarCollapsed.ts`), ~30 LOC.
- `Sidebar.tsx` and `AppShell.tsx` edited, not rewritten.
- Re-renders: toggling `settings.sidebarCollapsed` re-renders `AppShell` (grid class changes) and `Sidebar` (label visibility changes). No other subtree needs to update.

## Non-goals

- No animation on collapse/expand.
- No "peek on hover" / flyout expansion when collapsed.
- No per-route sidebar state (e.g., always expanded on Settings). Global toggle only.
- No remembering-last-viewport-state (e.g., "I collapsed it at narrow, expand when wide again"). One setting value, applied whenever the viewport permits.
- No localStorage migration — additive field.
- No separate "default" preference distinct from current state. Sticky-toggle semantics: the setting *is* the state.

## Open questions resolved during brainstorming

- **Setting semantics:** sticky-toggle (B). The setting is the state; chevron and Settings page write the same field.
- **Viewport breakpoint:** 768px (Tailwind `md`).
- **Toggle UI:** chevron in the sidebar header plus `Cmd/Ctrl+B` shortcut.
- **Collapsed rendering:** glyph-only centered, label `sr-only`, `title` tooltip.
