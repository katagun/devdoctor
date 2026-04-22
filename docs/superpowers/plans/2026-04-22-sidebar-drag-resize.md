# Draggable Sidebar Resize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the boolean sidebar-collapse state with a numeric `sidebarWidth`, add a draggable resize handle at the sidebar's right edge (with snap-to-collapsed near the minimum), and preserve the chevron + `Cmd/Ctrl+B` round-trip via a new `sidebarExpandedWidth` memory.

**Architecture:** Additive-then-cleanup. Add the new fields and the new hook/component alongside the old ones first (each task leaves typecheck + 56 tests green), migrate consumers one file at a time, then delete the obsolete boolean field and the old hook in a final cleanup task. Keeps the tree working after every commit and makes rollback trivial.

**Tech Stack:** TypeScript, React 18, Vite, Vitest + `@testing-library/react`, Tailwind 4. Same stack as prior features. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-04-22-sidebar-drag-resize-design.md`.

**Working directory for every command below:** the worktree the executor creates (e.g. `/Users/shamil/projects/github/katagun/diskdoctor/.worktrees/sidebar-drag-resize`). All `cd` commands use the worktree's `web/` subdir unless stated.

---

## Task 1: Extend `Settings` schema with `sidebarWidth` + `sidebarExpandedWidth` (additive)

**Files:**
- Modify: `web/src/hooks/useSettings.ts`

Additive-only. Old `sidebarCollapsed` stays for now (removed in Task 6). `read()` gets migration logic so users whose localStorage only has the old boolean get seeded into the new fields.

- [ ] **Step 1: Add a clamp helper + the two new fields to `Settings` and `DEFAULTS`**

In `web/src/hooks/useSettings.ts`, add near the top (after the existing `KEY` constant, before `CADENCE_PRESETS`):

```ts
// Sidebar width clamps. Min = icons-only state (matches the currently-shipped
// 48px collapsed width). Max = min(20% of viewport, 320px); recomputed from the
// live viewport on every read to keep stored values from exceeding the current
// display.
export const SIDEBAR_MIN_WIDTH = 48;
export const SIDEBAR_MAX_CAP = 320;
export const SIDEBAR_DEFAULT_WIDTH = 180;

export function sidebarMaxWidth(viewportWidth: number): number {
  return Math.min(Math.floor(viewportWidth * 0.2), SIDEBAR_MAX_CAP);
}

export function clampSidebarWidth(px: number, viewportWidth: number): number {
  const max = sidebarMaxWidth(viewportWidth);
  if (!Number.isFinite(px)) return SIDEBAR_DEFAULT_WIDTH;
  if (px < SIDEBAR_MIN_WIDTH) return SIDEBAR_MIN_WIDTH;
  if (px > max) return max;
  return Math.round(px);
}
```

Then find the `Settings` interface and update it:

```ts
export interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
  sidebarCollapsed: boolean;      // kept for backward compat; removed in Task 6
  sidebarWidth: number;
  sidebarExpandedWidth: number;
}
```

And `DEFAULTS`:

```ts
const DEFAULTS: Settings = {
  minSizeBytes: 0,
  cadence: "live",
  density: "sparse",
  theme: "system",
  sidebarCollapsed: false,
  sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
  sidebarExpandedWidth: SIDEBAR_DEFAULT_WIDTH,
};
```

- [ ] **Step 2: Update `read()` to parse the new fields with migration**

Replace the body of `read()` in `web/src/hooks/useSettings.ts` with:

```ts
function read(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULTS;

    const minSizeBytes =
      typeof parsed.minSizeBytes === "number" && parsed.minSizeBytes >= 0
        ? parsed.minSizeBytes
        : DEFAULTS.minSizeBytes;
    const cadence: CadenceId = CADENCE_PRESETS.some((c) => c.id === parsed.cadence)
      ? parsed.cadence
      : DEFAULTS.cadence;
    const density: Density = parsed.density === "dense" ? "dense" : DEFAULTS.density;
    const theme: Theme =
      parsed.theme === "light" || parsed.theme === "dark" || parsed.theme === "system"
        ? parsed.theme
        : DEFAULTS.theme;
    const sidebarCollapsed: boolean =
      typeof parsed.sidebarCollapsed === "boolean"
        ? parsed.sidebarCollapsed
        : DEFAULTS.sidebarCollapsed;

    // Sidebar width migration:
    //   * Prefer new fields when present and sensible.
    //   * Otherwise fall back to the old sidebarCollapsed boolean.
    //   * Otherwise default.
    const vw = typeof window === "undefined" ? 1024 : window.innerWidth;
    let sidebarWidth: number;
    let sidebarExpandedWidth: number;
    if (
      typeof parsed.sidebarWidth === "number" &&
      parsed.sidebarWidth >= SIDEBAR_MIN_WIDTH
    ) {
      sidebarWidth = clampSidebarWidth(parsed.sidebarWidth, vw);
      const parsedExpanded =
        typeof parsed.sidebarExpandedWidth === "number" &&
        parsed.sidebarExpandedWidth > SIDEBAR_MIN_WIDTH
          ? parsed.sidebarExpandedWidth
          : Math.max(sidebarWidth, SIDEBAR_DEFAULT_WIDTH);
      sidebarExpandedWidth = clampSidebarWidth(parsedExpanded, vw);
    } else if (typeof parsed.sidebarCollapsed === "boolean") {
      sidebarWidth = parsed.sidebarCollapsed
        ? SIDEBAR_MIN_WIDTH
        : SIDEBAR_DEFAULT_WIDTH;
      sidebarExpandedWidth = SIDEBAR_DEFAULT_WIDTH;
    } else {
      sidebarWidth = SIDEBAR_DEFAULT_WIDTH;
      sidebarExpandedWidth = SIDEBAR_DEFAULT_WIDTH;
    }

    return {
      minSizeBytes,
      cadence,
      density,
      theme,
      sidebarCollapsed,
      sidebarWidth,
      sidebarExpandedWidth,
    };
  } catch {
    return DEFAULTS;
  }
}
```

- [ ] **Step 3: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 4: Run existing tests**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 56 tests. No existing test asserts the shape of `Settings`, so adding two fields is invisible.

- [ ] **Step 5: Commit**

```bash
cd <worktree>
git add web/src/hooks/useSettings.ts
git commit -m "feat(web): add sidebarWidth + sidebarExpandedWidth to Settings

Additive change — existing sidebarCollapsed field stays for now so the
current useSidebarCollapsed hook keeps working. Task 6 removes the
old field. read() migrates old localStorage shapes (boolean-only) to
the new numeric fields on next read."
```

---

## Task 2: Create `useSidebarWidth` hook (TDD)

**Files:**
- Create: `web/src/hooks/useSidebarWidth.ts`
- Create: `web/tests/unit/useSidebarWidth.test.ts`

Lives alongside the existing `useSidebarCollapsed` hook until Task 6 deletes it. Consumers migrate one file at a time in Tasks 4 and 5.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/useSidebarWidth.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// matchMedia mock used across tests.
type Listener = (e: { matches: boolean }) => void;
interface FakeMediaQueryList {
  matches: boolean;
  addEventListener: (type: "change", fn: Listener) => void;
  removeEventListener: (type: "change", fn: Listener) => void;
  dispatchChange: (matches: boolean) => void;
  addListener: (fn: Listener) => void;
  removeListener: (fn: Listener) => void;
  media: string;
  onchange: null;
}

let mqls: FakeMediaQueryList[] = [];
function fakeMatchMedia(forceMatch: boolean) {
  return (query: string): FakeMediaQueryList => {
    const listeners = new Set<Listener>();
    const mql: FakeMediaQueryList = {
      matches: forceMatch && query.includes("max-width: 767px"),
      media: query,
      onchange: null,
      addEventListener: (type, fn) => {
        if (type === "change") listeners.add(fn);
      },
      removeEventListener: (type, fn) => {
        if (type === "change") listeners.delete(fn);
      },
      addListener: (fn) => listeners.add(fn),
      removeListener: (fn) => listeners.delete(fn),
      dispatchChange(matches: boolean) {
        this.matches = matches;
        listeners.forEach((l) => l({ matches }));
      },
    };
    mqls.push(mql);
    return mql;
  };
}

beforeEach(() => {
  localStorage.clear();
  mqls = [];
  vi.stubGlobal("matchMedia", fakeMatchMedia(false));
  vi.stubGlobal("innerWidth", 1440);
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSidebarWidth", () => {
  it("defaults to width=180, collapsed=false, expandedWidth=180", async () => {
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    expect(result.current.width).toBe(180);
    expect(result.current.collapsed).toBe(false);
    expect(result.current.forceCollapsedByViewport).toBe(false);
  });

  it("setWidth(240) persists the value and updates sidebarExpandedWidth", async () => {
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    act(() => result.current.setWidth(240));
    expect(result.current.width).toBe(240);
    expect(result.current.collapsed).toBe(false);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.sidebarWidth).toBe(240);
    expect(stored.sidebarExpandedWidth).toBe(240);
  });

  it("setWidth(50) clamps to 48 and does NOT update sidebarExpandedWidth", async () => {
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    // First drag to 240 so we have a meaningful "last expanded" to preserve.
    act(() => result.current.setWidth(240));
    // Now go below minimum.
    act(() => result.current.setWidth(50));
    expect(result.current.width).toBe(48);
    expect(result.current.collapsed).toBe(true);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.sidebarWidth).toBe(48);
    expect(stored.sidebarExpandedWidth).toBe(240); // unchanged
  });

  it("setWidth(9999) clamps to maxWidth", async () => {
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    act(() => result.current.setWidth(9999));
    // innerWidth stubbed to 1440 → max = min(288, 320) = 288.
    expect(result.current.width).toBe(288);
    expect(result.current.maxWidth).toBe(288);
  });

  it("toggle() when expanded collapses to 48 and preserves sidebarExpandedWidth", async () => {
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    act(() => result.current.setWidth(220));
    act(() => result.current.toggle());
    expect(result.current.width).toBe(48);
    expect(result.current.collapsed).toBe(true);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.sidebarExpandedWidth).toBe(220);
  });

  it("toggle() when collapsed expands back to sidebarExpandedWidth", async () => {
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    act(() => result.current.setWidth(220));
    act(() => result.current.toggle()); // collapse
    act(() => result.current.toggle()); // expand
    expect(result.current.width).toBe(220);
    expect(result.current.collapsed).toBe(false);
  });

  it("migrates old sidebarCollapsed=true to width=48", async () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ sidebarCollapsed: true }),
    );
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    expect(result.current.width).toBe(48);
    expect(result.current.collapsed).toBe(true);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.sidebarExpandedWidth).toBe(180);
  });

  it("viewport force-collapse: width=48, setWidth/toggle are no-ops", async () => {
    vi.stubGlobal("matchMedia", fakeMatchMedia(true));
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    expect(result.current.forceCollapsedByViewport).toBe(true);
    expect(result.current.width).toBe(48);
    act(() => result.current.setWidth(240));
    expect(result.current.width).toBe(48);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.sidebarWidth ?? 180).toBe(180); // untouched
  });

  it("matchMedia change event flips forceCollapsedByViewport live", async () => {
    const { useSidebarWidth } = await import("@/hooks/useSidebarWidth");
    const { result } = renderHook(() => useSidebarWidth());
    expect(result.current.forceCollapsedByViewport).toBe(false);

    const matching = mqls.filter((m) => m.media.includes("max-width: 767px"));
    expect(matching.length).toBeGreaterThan(0);
    act(() => matching.forEach((m) => m.dispatchChange(true)));

    expect(result.current.forceCollapsedByViewport).toBe(true);
    expect(result.current.width).toBe(48);
  });
});
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useSidebarWidth.test.ts
```

Expected: FAIL with a module-resolution error on `@/hooks/useSidebarWidth`.

- [ ] **Step 3: Implement the hook**

Create `web/src/hooks/useSidebarWidth.ts`:

```ts
import { useCallback, useEffect, useState } from "react";
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MIN_WIDTH,
  clampSidebarWidth,
  sidebarMaxWidth,
  useSettings,
} from "./useSettings";

const QUERY = "(max-width: 767px)";

function getInitialMatch(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(QUERY).matches;
}

function currentViewportWidth(): number {
  if (typeof window === "undefined") return 1024;
  return window.innerWidth;
}

export interface UseSidebarWidthResult {
  width: number;
  collapsed: boolean;
  setWidth: (px: number) => void;
  toggle: () => void;
  forceCollapsedByViewport: boolean;
  maxWidth: number;
}

export function useSidebarWidth(): UseSidebarWidthResult {
  const { settings, update } = useSettings();
  const [forceCollapsedByViewport, setForced] = useState<boolean>(getInitialMatch);
  const [viewportWidth, setViewportWidth] = useState<number>(currentViewportWidth);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(QUERY);
    setForced(mql.matches);
    const onChange = (e: MediaQueryListEvent | { matches: boolean }) => {
      setForced(e.matches);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const maxWidth = sidebarMaxWidth(viewportWidth);

  const setWidth = useCallback(
    (px: number) => {
      if (forceCollapsedByViewport) return;
      const clamped = clampSidebarWidth(px, viewportWidth);
      const patch: { sidebarWidth: number; sidebarExpandedWidth?: number } = {
        sidebarWidth: clamped,
      };
      if (clamped > SIDEBAR_MIN_WIDTH) {
        patch.sidebarExpandedWidth = clamped;
      }
      update(patch);
    },
    [forceCollapsedByViewport, viewportWidth, update],
  );

  const toggle = useCallback(() => {
    if (forceCollapsedByViewport) return;
    const collapsed = settings.sidebarWidth < 80;
    if (collapsed) {
      const target = clampSidebarWidth(
        settings.sidebarExpandedWidth || SIDEBAR_DEFAULT_WIDTH,
        viewportWidth,
      );
      update({ sidebarWidth: target });
    } else {
      update({ sidebarWidth: SIDEBAR_MIN_WIDTH });
    }
  }, [
    forceCollapsedByViewport,
    settings.sidebarWidth,
    settings.sidebarExpandedWidth,
    viewportWidth,
    update,
  ]);

  const effectiveWidth = forceCollapsedByViewport
    ? SIDEBAR_MIN_WIDTH
    : clampSidebarWidth(settings.sidebarWidth, viewportWidth);
  const collapsed = effectiveWidth < 80;

  return {
    width: effectiveWidth,
    collapsed,
    setWidth,
    toggle,
    forceCollapsedByViewport,
    maxWidth,
  };
}
```

- [ ] **Step 4: Run tests and watch them pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useSidebarWidth.test.ts
```

Expected: PASS — 9 tests, 0 failures.

- [ ] **Step 5: Run the full test suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 65 tests (56 prior + 9 new). `useSidebarCollapsed` tests still pass because the hook still exists.

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
git add web/src/hooks/useSidebarWidth.ts web/tests/unit/useSidebarWidth.test.ts
git commit -m "feat(web): useSidebarWidth hook backed by numeric settings

Lives alongside useSidebarCollapsed during migration. Consumers switch
over in later tasks; the old hook is deleted in Task 6."
```

---

## Task 3: Create `<SidebarResizeHandle>` component (TDD)

**Files:**
- Create: `web/src/components/SidebarResizeHandle.tsx`
- Create: `web/tests/unit/SidebarResizeHandle.test.tsx`

Standalone component. Not yet rendered by `<Sidebar>` — Task 5 plugs it in.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/SidebarResizeHandle.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SidebarResizeHandle } from "@/components/SidebarResizeHandle";

function renderHandle(props: Partial<React.ComponentProps<typeof SidebarResizeHandle>> = {}) {
  const setWidth = props.setWidth ?? vi.fn();
  const finalize = props.finalize ?? vi.fn();
  const width = props.width ?? 180;
  const maxWidth = props.maxWidth ?? 288;
  const hidden = props.hidden ?? false;
  render(
    <SidebarResizeHandle
      width={width}
      maxWidth={maxWidth}
      setWidth={setWidth}
      finalize={finalize}
      hidden={hidden}
    />,
  );
  return { setWidth, finalize };
}

describe("SidebarResizeHandle", () => {
  it("renders a separator with correct aria attributes", () => {
    renderHandle({ width: 180, maxWidth: 288 });
    const sep = screen.getByRole("separator");
    expect(sep).toBeInTheDocument();
    expect(sep.getAttribute("aria-orientation")).toBe("vertical");
    expect(sep.getAttribute("aria-label")).toBe("Resize sidebar");
    expect(sep.getAttribute("aria-valuenow")).toBe("180");
    expect(sep.getAttribute("aria-valuemin")).toBe("48");
    expect(sep.getAttribute("aria-valuemax")).toBe("288");
  });

  it("does not render when hidden=true", () => {
    renderHandle({ hidden: true });
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  });

  it("pointerdown + move updates width via setWidth", () => {
    const { setWidth } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    fireEvent.pointerDown(sep, { clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(sep, { clientX: 260, pointerId: 1 });
    // startWidth 180 + (260 - 200) = 240
    expect(setWidth).toHaveBeenCalledWith(240);
  });

  it("pointerup above the snap threshold calls finalize with the current width", () => {
    const { setWidth, finalize } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    fireEvent.pointerDown(sep, { clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(sep, { clientX: 260, pointerId: 1 });
    fireEvent.pointerUp(sep, { clientX: 260, pointerId: 1 });
    expect(setWidth).toHaveBeenLastCalledWith(240);
    expect(finalize).toHaveBeenCalledWith(240);
  });

  it("pointerup below the snap threshold (<80) calls finalize(48) to snap", () => {
    const { setWidth, finalize } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    fireEvent.pointerDown(sep, { clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(sep, { clientX: 60, pointerId: 1 }); // 180 + (60-200) = 40
    // setWidth call for the move will have clamped to 48 inside the hook's setter,
    // but the handle itself calls setWidth with the raw (negative-ish) delta.
    // What we care about here is the snap on release:
    fireEvent.pointerUp(sep, { clientX: 60, pointerId: 1 });
    expect(finalize).toHaveBeenCalledWith(48);
    void setWidth; // silence unused
  });

  it("ArrowLeft decreases width by 16 via setWidth", () => {
    const { setWidth } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    fireEvent.keyDown(sep, { key: "ArrowLeft" });
    expect(setWidth).toHaveBeenCalledWith(164);
  });

  it("ArrowRight increases width by 16 via setWidth", () => {
    const { setWidth } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    fireEvent.keyDown(sep, { key: "ArrowRight" });
    expect(setWidth).toHaveBeenCalledWith(196);
  });

  it("Home jumps to 48 and End jumps to maxWidth", () => {
    const { setWidth } = renderHandle({ width: 180, maxWidth: 288 });
    const sep = screen.getByRole("separator");
    fireEvent.keyDown(sep, { key: "Home" });
    expect(setWidth).toHaveBeenCalledWith(48);
    fireEvent.keyDown(sep, { key: "End" });
    expect(setWidth).toHaveBeenCalledWith(288);
  });
});
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/SidebarResizeHandle.test.tsx
```

Expected: FAIL with a module-resolution error.

- [ ] **Step 3: Implement the component**

Create `web/src/components/SidebarResizeHandle.tsx`:

```tsx
import { useRef } from "react";

const SNAP_THRESHOLD = 80;
const COLLAPSED_WIDTH = 48;
const KEY_STEP = 16;

export interface SidebarResizeHandleProps {
  width: number;
  maxWidth: number;
  setWidth: (px: number) => void;
  finalize: (px: number) => void;
  hidden?: boolean;
}

export function SidebarResizeHandle({
  width,
  maxWidth,
  setWidth,
  finalize,
  hidden = false,
}: SidebarResizeHandleProps) {
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null);
  const lastWidthRef = useRef<number>(width);
  lastWidthRef.current = width;

  if (hidden) return null;

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    dragState.current = { startX: e.clientX, startWidth: width };
    // setPointerCapture isn't always implemented in jsdom; guard it.
    if (typeof e.currentTarget.setPointerCapture === "function") {
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        /* ignore — move/up handlers still fire on the same element */
      }
    }
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragState.current) return;
    const next = dragState.current.startWidth + (e.clientX - dragState.current.startX);
    setWidth(next);
  }

  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragState.current) return;
    const rawFinal = dragState.current.startWidth + (e.clientX - dragState.current.startX);
    dragState.current = null;
    if (typeof e.currentTarget.releasePointerCapture === "function") {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    }
    // Snap-to-collapsed: below the threshold, finalize at the collapsed width.
    if (rawFinal < SNAP_THRESHOLD) {
      finalize(COLLAPSED_WIDTH);
    } else {
      // Clamp the final value against maxWidth to match what the hook accepted.
      const finalWidth = Math.max(
        COLLAPSED_WIDTH,
        Math.min(rawFinal, maxWidth),
      );
      finalize(finalWidth);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    switch (e.key) {
      case "ArrowLeft":
        e.preventDefault();
        setWidth(width - KEY_STEP);
        break;
      case "ArrowRight":
        e.preventDefault();
        setWidth(width + KEY_STEP);
        break;
      case "Home":
        e.preventDefault();
        setWidth(COLLAPSED_WIDTH);
        break;
      case "End":
        e.preventDefault();
        setWidth(maxWidth);
        break;
    }
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuenow={width}
      aria-valuemin={COLLAPSED_WIDTH}
      aria-valuemax={maxWidth}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
      className="absolute top-0 bottom-0 w-1 -right-0.5 cursor-col-resize hover:bg-border-strong focus:bg-border-strong focus:outline-none"
    />
  );
}
```

- [ ] **Step 4: Run tests and watch them pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/SidebarResizeHandle.test.tsx
```

Expected: PASS — 8 tests.

- [ ] **Step 5: Run the full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 73 tests (65 prior + 8 new).

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
git add web/src/components/SidebarResizeHandle.tsx web/tests/unit/SidebarResizeHandle.test.tsx
git commit -m "feat(web): SidebarResizeHandle with pointer + keyboard support

Standalone component with separator a11y semantics, pointer-drag that
reports width changes via setWidth, snap-to-collapsed finalize on
release below 80px, and keyboard support (arrows, Home, End). Plugged
into Sidebar in Task 5."
```

---

## Task 4: Migrate `AppShell` to `useSidebarWidth`

**Files:**
- Modify: `web/src/AppShell.tsx`

- [ ] **Step 1: Replace the hook import and derive the grid template inline**

Replace the ENTIRE contents of `web/src/AppShell.tsx` with:

```tsx
import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { useApplyTheme } from "./hooks/useApplyTheme";
import { useSidebarWidth } from "./hooks/useSidebarWidth";

const MAC_LIKE = /^Mac/.test(
  typeof navigator !== "undefined" ? navigator.platform : "",
);

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export default function AppShell() {
  useApplyTheme();
  const { width, toggle, forceCollapsedByViewport } = useSidebarWidth();

  useEffect(() => {
    function onKeydown(e: KeyboardEvent) {
      if (forceCollapsedByViewport) return;
      if (e.key !== "b" && e.key !== "B") return;
      const modifier = MAC_LIKE ? e.metaKey : e.ctrlKey;
      if (!modifier) return;
      if (e.altKey || e.shiftKey) return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      toggle();
    }
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, [toggle, forceCollapsedByViewport]);

  return (
    <div
      className="min-h-screen grid bg-bg text-text font-sans"
      style={{ gridTemplateColumns: `${width}px 1fr` }}
    >
      <Sidebar />
      <main className="flex flex-col min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 3: Run the full test suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — all 73 tests still green. AppShell isn't covered by any test; the Sidebar still uses `useSidebarCollapsed` (both hooks read from the same settings so they stay in agreement — toggling from AppShell via the new hook updates `sidebarWidth`, which the old hook now ignores but since its derived `collapsed` reads the old `sidebarCollapsed` boolean, the Sidebar rendering is briefly decoupled from AppShell's width until Task 5. This is expected during migration and does not break tests.)

- [ ] **Step 4: Commit**

```bash
cd <worktree>
git add web/src/AppShell.tsx
git commit -m "refactor(web): AppShell consumes useSidebarWidth

Grid template becomes inline-styled from the numeric width. Keyboard
shortcut now calls the new toggle (collapsed ↔ last expanded width)."
```

---

## Task 5: Migrate `Sidebar` to `useSidebarWidth` + render `<SidebarResizeHandle>`

**Files:**
- Modify: `web/src/components/Sidebar.tsx`
- Modify: `web/tests/unit/Sidebar.test.tsx`

- [ ] **Step 1: Update `Sidebar.test.tsx` for the new localStorage shape**

In `web/tests/unit/Sidebar.test.tsx`:

1. Replace the two `localStorage.setItem("diskdoctor.settings.v1", JSON.stringify({ sidebarCollapsed: true }))` calls inside the two `when collapsed` `beforeEach` blocks with:

   ```ts
   localStorage.setItem(
     "diskdoctor.settings.v1",
     JSON.stringify({ sidebarWidth: 48, sidebarExpandedWidth: 180 }),
   );
   ```

2. The existing comment `// Force matchMedia to match so useSidebarCollapsed sees forceCollapsedByViewport=true` is now slightly stale; change `useSidebarCollapsed` → `useSidebarWidth` in that comment only.

Everything else stays the same — the tests assert behaviour through `screen.getByRole(...)`, which is not coupled to the hook name.

- [ ] **Step 2: Run Sidebar tests — they should fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: FAIL. The Sidebar still imports `useSidebarCollapsed`, which reads the old `sidebarCollapsed` field — the new localStorage shape we seeded has no `sidebarCollapsed: true`, so the old hook sees `false` and the "when collapsed" tests fail.

- [ ] **Step 3: Replace `Sidebar.tsx`**

Replace the ENTIRE contents of `web/src/components/Sidebar.tsx` with:

```tsx
import { NavLink } from "react-router-dom";
import { SidebarResizeHandle } from "@/components/SidebarResizeHandle";
import { useSidebarWidth } from "@/hooks/useSidebarWidth";

const linkBase =
  "flex items-center px-3 py-1.5 rounded text-[10.5px] font-mono transition-colors";
const linkActive = "bg-bg-elev-2 text-text";
const linkIdle = "text-text-dim hover:bg-bg-elev-1";

function Item({
  to,
  glyph,
  label,
  count,
  collapsed,
}: {
  to: string;
  glyph: string;
  label: string;
  count?: number;
  collapsed: boolean;
}) {
  const alignment = collapsed ? "justify-center" : "justify-between";
  return (
    <NavLink
      to={to}
      end={to === "/"}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        `${linkBase} ${alignment} ${isActive ? linkActive : linkIdle}`
      }
    >
      {collapsed ? (
        <>
          <span aria-hidden="true">{glyph}</span>
          <span className="sr-only">{label}</span>
        </>
      ) : (
        <>
          <span>
            <span aria-hidden="true">{glyph}</span> {label}
          </span>
          {count !== undefined && (
            <span className="text-text-muted text-[9.5px]">{count}</span>
          )}
        </>
      )}
    </NavLink>
  );
}

function ChevronToggle({
  collapsed,
  onClick,
}: {
  collapsed: boolean;
  onClick: () => void;
}) {
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-expanded={!collapsed}
      className="text-text-muted hover:text-text text-[11px] px-1 leading-none"
    >
      {collapsed ? "▶" : "◀"}
    </button>
  );
}

export function Sidebar() {
  const { width, collapsed, setWidth, toggle, maxWidth, forceCollapsedByViewport } =
    useSidebarWidth();

  return (
    <aside className="bg-bg-elev-1 border-r border-border p-3 sticky top-0 h-screen relative">
      <div
        className={`flex gap-2 items-center pb-3 mb-4 border-b border-border ${
          collapsed ? "flex-col" : ""
        }`}
      >
        <div className={`flex items-center gap-2 ${collapsed ? "" : "flex-1"}`}>
          <span
            className="w-[7px] h-[7px] rounded-full bg-risk-reclaim"
            style={{ boxShadow: "0 0 10px var(--risk-reclaim)" }}
          />
          {!collapsed && (
            <span className="font-mono font-semibold text-[12px]">diskdoctor</span>
          )}
        </div>
        {!forceCollapsedByViewport && (
          <ChevronToggle collapsed={collapsed} onClick={toggle} />
        )}
      </div>
      {!collapsed && (
        <div className="text-text-muted text-[9px] uppercase tracking-widest px-2 pb-1">
          workspace
        </div>
      )}
      <nav className="flex flex-col gap-0.5 mb-4">
        <Item to="/" glyph="◆" label="scan" collapsed={collapsed} />
        <Item to="/snapshots" glyph="⏱" label="snapshots" collapsed={collapsed} />
        <Item to="/history" glyph="≡" label="history" collapsed={collapsed} />
        <Item to="/providers" glyph="⚙" label="providers" collapsed={collapsed} />
        <Item to="/settings" glyph="⚡" label="settings" collapsed={collapsed} />
      </nav>
      <SidebarResizeHandle
        width={width}
        maxWidth={maxWidth}
        setWidth={setWidth}
        finalize={setWidth}
        hidden={forceCollapsedByViewport}
      />
    </aside>
  );
}
```

Notes:
- `<aside>` gains `relative` so the absolute-positioned handle anchors to it.
- `finalize={setWidth}` — the handle's snap-on-release goes through the hook's same setter. The hook's clamp handles validation; the handle's snap converts sub-80 releases to the exact collapsed width of 48.

IMPORTANT: Use real unicode glyphs (◆, ⏱, ≡, ⚙, ⚡, ▶, ◀) in the JSX — not escape sequences.

- [ ] **Step 4: Run Sidebar tests — they should pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: PASS — 8 tests.

- [ ] **Step 5: Run the full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 73 tests.

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
git add web/src/components/Sidebar.tsx web/tests/unit/Sidebar.test.tsx
git commit -m "feat(web): Sidebar uses useSidebarWidth + drag handle

Render tracks the effective width (via derived collapsed boolean);
SidebarResizeHandle plugs in at the right edge for continuous drag.
Tests reseed localStorage with the new width shape."
```

---

## Task 6: Remove obsolete `sidebarCollapsed` / `useSidebarCollapsed` / Settings-page chip

**Files:**
- Modify: `web/src/hooks/useSettings.ts`
- Modify: `web/src/pages/Settings.tsx`
- Delete: `web/src/hooks/useSidebarCollapsed.ts`
- Delete: `web/tests/unit/useSidebarCollapsed.test.ts`

Nothing consumes `useSidebarCollapsed` or `settings.sidebarCollapsed` anymore after Tasks 4 and 5. Clean up.

- [ ] **Step 1: Remove the `Sidebar` Section from `Settings.tsx`**

Edit `web/src/pages/Settings.tsx`. Delete the entire block:

```tsx
      <Section
        title="Sidebar"
        description="Collapse the sidebar to icons only. Narrow viewports (below 768px) always collapse, regardless of this setting."
      >
        <div className="flex gap-2">
          <Chip
            active={!settings.sidebarCollapsed}
            onClick={() => applyAndFlash({ sidebarCollapsed: false })}
          >
            expanded
          </Chip>
          <Chip
            active={settings.sidebarCollapsed}
            onClick={() => applyAndFlash({ sidebarCollapsed: true })}
          >
            collapsed
          </Chip>
        </div>
      </Section>
```

No replacement — the feature is driven by drag + chevron + shortcut.

- [ ] **Step 2: Drop `sidebarCollapsed` from the `Settings` interface and `DEFAULTS`**

In `web/src/hooks/useSettings.ts`:

The `Settings` interface becomes:

```ts
export interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
  sidebarWidth: number;
  sidebarExpandedWidth: number;
}
```

And `DEFAULTS`:

```ts
const DEFAULTS: Settings = {
  minSizeBytes: 0,
  cadence: "live",
  density: "sparse",
  theme: "system",
  sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
  sidebarExpandedWidth: SIDEBAR_DEFAULT_WIDTH,
};
```

- [ ] **Step 3: Update `read()` to drop `sidebarCollapsed` from the return shape**

In `web/src/hooks/useSettings.ts`, the `read()` function's return statement becomes:

```ts
return {
  minSizeBytes,
  cadence,
  density,
  theme,
  sidebarWidth,
  sidebarExpandedWidth,
};
```

Also remove these lines inside `read()` that were computing the dropped field:

```ts
const sidebarCollapsed: boolean =
  typeof parsed.sidebarCollapsed === "boolean"
    ? parsed.sidebarCollapsed
    : DEFAULTS.sidebarCollapsed;
```

The migration block that FALLS BACK to reading `parsed.sidebarCollapsed` when no new fields exist stays — it continues to migrate old users' localStorage on first read.

- [ ] **Step 4: Delete the obsolete hook and its test**

Run:
```bash
cd <worktree>
rm web/src/hooks/useSidebarCollapsed.ts web/tests/unit/useSidebarCollapsed.test.ts
```

- [ ] **Step 5: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS. Nothing in the codebase still imports `useSidebarCollapsed` or reads `settings.sidebarCollapsed`.

- [ ] **Step 6: Run the full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 68 tests (73 from Task 5 minus 5 from the deleted `useSidebarCollapsed.test.ts`).

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add -A web/src/hooks/useSettings.ts web/src/pages/Settings.tsx web/src/hooks/useSidebarCollapsed.ts web/tests/unit/useSidebarCollapsed.test.ts
git commit -m "refactor(web): drop sidebarCollapsed field + useSidebarCollapsed hook

All consumers migrated to useSidebarWidth. Settings-page chip removed;
drag + chevron + shortcut are the sidebar controls now. Migration
fallback in read() stays so old localStorage still parses."
```

---

## Task 7: Build, visual check, keyboard/drag verification

- [ ] **Step 1: Production build**

Run:
```bash
cd <worktree>/web
npm run build
```

Expected: clean build. Bundle size roughly unchanged.

- [ ] **Step 2: Full test sweep**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: ALL PASS — 68 tests total (43 baseline + 9 useSidebarWidth + 8 SidebarResizeHandle + 8 Sidebar).

- [ ] **Step 3: Dev server + manual check**

Run:
```bash
cd <worktree>/web
npm run dev
```

Verify in the browser:

1. **Default width**: sidebar renders at 180px with labels.
2. **Drag slow**: press on the right edge of the sidebar, drag right — sidebar widens continuously up to the cap (288px on 1440px displays, 320px on larger).
3. **Drag left past threshold**: drag the edge left — below ~80px, release snaps to 48 (icons only).
4. **Drag left, release above threshold**: release at 120px — sidebar stays at 120px, labels still showing.
5. **Round-trip via chevron**: drag to 240px. Click chevron. Sidebar collapses to 48. Click again. Sidebar returns to 240px.
6. **Round-trip via shortcut**: same as (5) but with `Cmd+B` (macOS) or `Ctrl+B` (Linux/Windows). Skips when focus is in a text input.
7. **Keyboard on handle**: focus the resize handle (Tab through until it has the highlight). `ArrowLeft` / `ArrowRight` shrink / grow by 16px. `Home` collapses. `End` jumps to max.
8. **Narrow viewport**: shrink the browser window below 768px — sidebar force-collapses to 48, chevron disappears, drag handle disappears, keyboard shortcut is a no-op. Widen again — sidebar returns to the last stored width.
9. **Reload persistence**: set width to 240, reload — still 240.
10. **Settings page**: the "Sidebar" Section is gone. "Reset to defaults" still restores sidebar to 180.
11. **Migration (clean localStorage first)**: in devtools, set `localStorage['diskdoctor.settings.v1'] = JSON.stringify({ sidebarCollapsed: true })` then reload — sidebar is at 48. Toggle via chevron — returns to 180.

- [ ] **Step 4: Confirm no regressions in other UI**

Spot-check:
- Provider icons still render on Scan / Snapshots / Providers / Wizard review.
- Disk-usage bar refreshes after cleanup/scan/snapshot (bug fixed earlier).
- Theme toggle still works.
- Cleanup wizard still advances.

- [ ] **Step 5: Final commit (only if touch-ups happened)**

If no changes made in this task, skip. Otherwise stage and commit.

---

## Out of scope

- Animation on collapse snap.
- Touch-drag (narrow viewports force-collapse, so drag doesn't apply there).
- Double-click-handle-to-toggle.
- Width tooltip during drag.
- Per-route sidebar width.
- rAF-throttling the drag handler (deferred until profiling shows jank).

## Rollback

Each commit is self-contained. Reverse order rolls the feature back task-by-task:

```bash
cd <worktree>
git log --oneline main..HEAD
# git revert each SHA in reverse order
```

No data migration in the destructive sense — the `read()` fallback continues to handle the old `sidebarCollapsed: true/false` shape even after Task 6's removal of the field, so a revert doesn't corrupt user state.
