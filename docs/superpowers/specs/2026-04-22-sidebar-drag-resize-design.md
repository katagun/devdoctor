# Draggable sidebar resize — design

Date: 2026-04-22
Status: approved for implementation plan

## Goal

Let the user drag the right edge of the sidebar to resize it continuously between an icons-only minimum (48px) and a practical maximum (20% of viewport, capped at 320px). Replaces the boolean `sidebarCollapsed` state shipped last feature with a numeric `sidebarWidth`. The chevron button and `Cmd/Ctrl+B` keyboard shortcut keep working; they now toggle between collapsed and the user's last non-collapsed width.

## State model

Replace `sidebarCollapsed: boolean` on `Settings` with two numeric fields:

```ts
interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
  sidebarWidth: number;          // current width. Default: 180.
  sidebarExpandedWidth: number;  // what "expand" restores to. Default: 180.
}
```

- `sidebarWidth` drives the layout. When collapsed, it is 48.
- `sidebarExpandedWidth` is the "last non-collapsed width the user was happy with." Updated any time the user drags to a width > 48. Used as the target when `toggle()` expands a collapsed sidebar.
- Both are clamped to `[48, min(viewport * 0.20, 320)]` on every write.
- `DEFAULTS` set both to 180.
- `reset()` resets both to 180.

### Derived values

- `collapsed === (sidebarWidth < 80)` — single threshold, used by layout, rendering, `aria-expanded`, and the drag handle's snap rule. The 80-not-48 buffer matches the snap-to-collapsed gesture, so during a drag the label/icon rendering state and the "this will snap" state always agree.
- Rendering: sidebar shows icons-only iff `collapsed`. Anything ≥ 80 shows labels.

## Hook: `useSidebarWidth` (renamed from `useSidebarCollapsed`)

```ts
interface UseSidebarWidthResult {
  width: number;                          // effective width (viewport-override aware)
  collapsed: boolean;                     // derived: width < 80
  setWidth: (px: number) => void;         // clamps, persists; no snap inside the hook
  toggle: () => void;                     // collapsed → sidebarExpandedWidth, else → 48
  forceCollapsedByViewport: boolean;
  maxWidth: number;                       // current max given viewport; handle clamps here
}
```

Behavior:

- `setWidth(px)` clamps to `[48, maxWidth]`, writes to `sidebarWidth`. If the clamped value is > 48, also writes `sidebarExpandedWidth = clamped`. If `forceCollapsedByViewport`, it's a no-op.
- `toggle()`: if `collapsed`, sets `sidebarWidth = sidebarExpandedWidth`. Otherwise sets `sidebarWidth = 48` (does NOT touch `sidebarExpandedWidth`). No-op when forced.
- `forceCollapsedByViewport` tracks `matchMedia("(max-width: 767px)")` exactly as today. When true, `width` returns 48 regardless of the stored value.
- `maxWidth` is recomputed on every viewport resize (via a window `resize` listener or `matchMedia` on a coarser breakpoint) so the handle's drag clamp stays current on window-resize.

**Snapping does NOT live in the hook.** The hook only clamps. The drag handle component is responsible for the "release below 80 → snap to 48" behavior — that's a UI gesture, not a state rule. The `< 80` threshold is the same one `collapsed` uses, so rendering and gesture agree throughout the drag.

## Drag handle: `<SidebarResizeHandle>`

New component rendered inside `<Sidebar>`, absolute-positioned at the sidebar's right edge.

### Interaction

- 4px-wide vertical strip (`width: 4px; position: absolute; top: 0; right: -2px; bottom: 0`).
- Cursor `col-resize` on hover.
- Subtle hover highlight (`hover:bg-border-strong`); focused state has the same highlight.
- `onPointerDown`:
  1. `setPointerCapture(event.pointerId)`.
  2. Record `startX = event.clientX`, `startWidth = width`.
  3. Attach `pointermove` + `pointerup` listeners to the handle element (pointer capture routes them back reliably).
- `onPointerMove`:
  1. Compute `next = startWidth + (event.clientX - startX)`.
  2. Clamp to `[48, maxWidth]`.
  3. Call `setWidth(next)` — realtime rendering updates.
- `onPointerUp`:
  1. If final `width < 80`, call `setWidth(48)` to snap to the collapsed state.
  2. Release pointer capture, remove listeners.
- Cancelled or lost-capture: same cleanup, no snap.

### Accessibility

- `role="separator"` with `aria-orientation="vertical"`.
- `aria-label="Resize sidebar"`.
- `aria-valuenow={width}`, `aria-valuemin={48}`, `aria-valuemax={maxWidth}`.
- Keyboard support when focused:
  - `ArrowLeft` → `setWidth(width - 16)`
  - `ArrowRight` → `setWidth(width + 16)`
  - `Home` → `setWidth(48)`
  - `End` → `setWidth(maxWidth)`
- Hidden (not rendered) when `forceCollapsedByViewport`.

### Visual

When user is actively dragging (pointer held), add a class like `bg-border-strong` for unambiguous feedback. Remove on release.

## Layout (`AppShell.tsx`)

Replace the class-based grid flip with an inline style driven by `width`:

```tsx
const { width } = useSidebarWidth();
return (
  <div
    className="min-h-screen grid bg-bg text-text font-sans"
    style={{ gridTemplateColumns: `${width}px 1fr` }}
  >
    <Sidebar />
    <main className="flex flex-col min-w-0"><Outlet /></main>
  </div>
);
```

No Tailwind class flip, no CSS transition — drag is already a continuous animation in itself, and tables inside `<main>` benefit from instant reflow.

## Sidebar rendering

Consumes `useSidebarWidth` (was `useSidebarCollapsed`). The rendering switch is still `collapsed ? iconsOnly : iconsAndLabels` — the only difference is that `collapsed` is now derived from `width < 80` instead of a stored boolean. Chevron button renders when `!forceCollapsedByViewport`, same as today; `aria-expanded={!collapsed}`; click calls `toggle()`.

Sidebar adds the `<SidebarResizeHandle>` at the right edge, positioned absolutely inside `<aside>`.

## Keyboard shortcut (`AppShell`)

Unchanged mechanism (Cmd on macOS, Ctrl elsewhere, skip editable targets, skip when forced). Now calls `toggle()` from `useSidebarWidth`, which has the remembered-width semantics.

## Settings page

Remove the `Sidebar` `Section` added in the previous feature. No sidebar control surface on Settings. `reset()` still restores the defaults via the global reset button.

## Migration

Old localStorage schemas in the wild have `sidebarCollapsed: boolean`. `read()` in `useSettings.ts` handles both shapes:

```ts
// Preferred: new fields present and valid.
if (typeof parsed.sidebarWidth === "number" && parsed.sidebarWidth >= 48) {
  sidebarWidth = clamp(parsed.sidebarWidth);
  sidebarExpandedWidth =
    typeof parsed.sidebarExpandedWidth === "number" && parsed.sidebarExpandedWidth > 48
      ? clamp(parsed.sidebarExpandedWidth)
      : Math.max(sidebarWidth, 180);
}
// Fallback: old boolean present.
else if (typeof parsed.sidebarCollapsed === "boolean") {
  sidebarWidth = parsed.sidebarCollapsed ? 48 : 180;
  sidebarExpandedWidth = 180;
}
// Default.
else {
  sidebarWidth = 180;
  sidebarExpandedWidth = 180;
}
```

Migration is one-shot: the next `setStore(...)` write persists the new schema and the old field is dropped.

## Narrow-viewport behavior

Unchanged from today:
- `matchMedia("(max-width: 767px)")` match ⇒ `forceCollapsedByViewport = true`.
- `width` returns 48 regardless of stored value.
- `SidebarResizeHandle` and chevron are hidden.
- `setWidth` and `toggle` are no-ops.
- Stored `sidebarWidth` preserved; re-applied when the viewport widens.

## Accessibility summary

- Drag handle has `role="separator"`, keyboard support, full `aria-value*` triplet.
- Chevron still has dynamic `aria-label` and `aria-expanded`.
- Nav items keep their collapsed-mode `sr-only` labels and `title` tooltip behaviour.
- No focus loss on collapse — the chevron stays focusable in both states.

## Testing

### `web/tests/unit/useSidebarWidth.test.ts` (rename + expand)

Replace the old `useSidebarCollapsed.test.ts` content with:

- Default: `width === 180`, `collapsed === false`, `sidebarExpandedWidth === 180`.
- `setWidth(240)` persists 240; `collapsed === false`; `sidebarExpandedWidth === 240`.
- `setWidth(50)` clamps to 48 (below min); `collapsed === true`; `sidebarExpandedWidth` unchanged.
- `setWidth(9999)` clamps to `maxWidth`; `sidebarExpandedWidth` updates to clamped value.
- `toggle()` when expanded: `width === 48`; `sidebarExpandedWidth` unchanged.
- `toggle()` when collapsed: `width === sidebarExpandedWidth`; setting persists.
- `toggle()` round-trips: drag to 240 → toggle → 48 → toggle → 240.
- Migration: localStorage `{ sidebarCollapsed: true }` yields `width: 48`, `sidebarExpandedWidth: 180`.
- Migration: localStorage `{ sidebarCollapsed: false }` yields `width: 180`, `sidebarExpandedWidth: 180`.
- Viewport forcing: matchMedia matches → `setWidth(240)` is a no-op, stored value unchanged; `width === 48` via override; when matchMedia stops matching, stored value re-applies.

### `web/tests/unit/SidebarResizeHandle.test.tsx` (new)

- Renders with `role="separator"`, `aria-orientation="vertical"`, and correct `aria-value*` attributes.
- Simulating `pointerdown` → `pointermove(clientX += 60)` → `pointerup` yields `setWidth(startWidth + 60)` followed by no snap (release above 80).
- Simulating release below 80 yields a `setWidth(48)` call after the last move.
- Keyboard `ArrowLeft` / `ArrowRight` adjust width by 16.
- Keyboard `Home` / `End` jump to 48 / `maxWidth`.
- Not rendered when `forceCollapsedByViewport` is true.

### `web/tests/unit/Sidebar.test.tsx` (update)

Update existing 8 tests to the renamed hook and new localStorage shape:
- Seed `{ sidebarWidth: 48 }` where tests previously used `{ sidebarCollapsed: true }`.
- Seed default for expanded-mode tests.
- Chevron tests unchanged structurally — button still renders based on `collapsed`, aria-expanded flips the same way.
- Remove any assertion that depended on the boolean field being in localStorage.

### No e2e

Drag gestures are unit-testable through synthetic `PointerEvent`s; the integration path is small and covered by the hook + handle tests.

## Bundle and performance

- No new dependencies. Pointer events are platform APIs.
- One new component (`SidebarResizeHandle`, ~80 lines), one updated hook (`useSidebarWidth`, ~60 lines after rename + clamp logic), a few tweaks to `AppShell`, `Sidebar`, `useSettings`.
- Drag performance: `setWidth` on every `pointermove` triggers a React re-render of `AppShell` and `Sidebar`. Both trees are small; this is the same mechanism any draggable split-pane uses. If profiling shows jank on slow machines, we can rAF-throttle the handle's move handler later — deferred until observed.

## Non-goals

- No "reset to default width" button outside the global `reset()` on Settings.
- No per-route sidebar width.
- No animation on the collapse snap — the snap is instant on pointer release.
- No touch-drag support. Narrow viewports force-collapse, so drag isn't applicable there.
- No double-click-to-toggle on the handle. One gesture, one meaning.
- No width tooltip during drag. Bounds are reflected by the drag naturally stopping.
- No minimum-width increase beyond 48 when labels can't fit. Labels hide below width 60; that's the whole UX.

## Open questions resolved during brainstorming

- **State model:** Replace boolean with numeric `sidebarWidth` (Q1 → A).
- **Bounds:** `min(viewport * 0.20, 320)`, min 48 (Q2 → B).
- **Snap behavior:** Gravity well near collapsed (< 80 on release → 48). No other snap points. Same threshold drives the `collapsed` derived value, so drag-render and snap-gesture agree (Q3 → B).
- **Keyboard shortcut:** Toggle remembers last non-collapsed width via `sidebarExpandedWidth` (Q4 → A).
- **Settings page:** Drop the chip pair entirely (Q5 → A).
- **Narrow viewport:** Keep existing force-collapse rule unchanged (Q6 → A).
