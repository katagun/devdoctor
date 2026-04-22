# Collapsible Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sticky-toggle collapsed mode to the sidebar (48px icons-only), with a chevron control in the sidebar header, a Cmd/Ctrl+B keyboard shortcut, an auto-collapse rule for viewports under 768px, and a matching chip pair on the Settings page.

**Architecture:** One new setting field (`sidebarCollapsed: boolean`) on the existing `Settings` type, one new hook (`useSidebarCollapsed`) that layers a `matchMedia`-driven viewport override on top of the setting, and targeted edits to `AppShell`, `Sidebar`, and `Settings`. No backend changes, no new dependencies.

**Tech Stack:** TypeScript, React 18, Vite, Vitest + `@testing-library/react`, Tailwind 4. Same stack as provider-icons work.

**Source spec:** `docs/superpowers/specs/2026-04-22-sidebar-collapse-design.md`.

**Working directory for every command below:** the worktree the executor creates for this feature (e.g. `/Users/shamil/projects/github/katagun/diskdoctor/.worktrees/sidebar-collapse`). All `cd` commands use the worktree's `web/` subdir unless stated.

---

## Task 1: Extend `Settings` schema with `sidebarCollapsed`

**Files:**
- Modify: `web/src/hooks/useSettings.ts`

Purely additive — adds a field with a safe default. No test needed in isolation because downstream tasks exercise it end-to-end; writing a standalone test of the reducer logic would be testing `useSyncExternalStore` plumbing we don't own.

- [ ] **Step 1: Add field to the `Settings` interface**

In `web/src/hooks/useSettings.ts`, find the `Settings` interface (around line 29):

```ts
export interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
}
```

Change to:

```ts
export interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
  sidebarCollapsed: boolean;
}
```

- [ ] **Step 2: Add default value**

Find `DEFAULTS` (around line 36):

```ts
const DEFAULTS: Settings = {
  minSizeBytes: 0,
  cadence: "live",
  density: "sparse",
  theme: "system",
};
```

Change to:

```ts
const DEFAULTS: Settings = {
  minSizeBytes: 0,
  cadence: "live",
  density: "sparse",
  theme: "system",
  sidebarCollapsed: false,
};
```

- [ ] **Step 3: Parse field in `read()`**

Find the `read()` function (around line 43). Add parsing for `sidebarCollapsed` alongside the other fields. Replace the body of `read()` with:

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
    return { minSizeBytes, cadence, density, theme, sidebarCollapsed };
  } catch {
    return DEFAULTS;
  }
}
```

- [ ] **Step 4: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS. The existing `update()` and `reset()` both already pattern-match on `Settings`, so adding a field is transparent to them.

- [ ] **Step 5: Run existing tests to confirm no regression**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 43 tests, 0 failures. No existing test asserts shape of `Settings`, so the schema bump is invisible.

- [ ] **Step 6: Commit**

```bash
cd <worktree>
git add web/src/hooks/useSettings.ts
git commit -m "feat(web): add sidebarCollapsed field to Settings schema"
```

---

## Task 2: Create `useSidebarCollapsed` hook (TDD)

**Files:**
- Create: `web/src/hooks/useSidebarCollapsed.ts`
- Create: `web/tests/unit/useSidebarCollapsed.test.ts`

**Context:** This hook is the single source of truth for collapse state across `AppShell`, `Sidebar`, and future consumers. It resolves the effective state by layering `matchMedia("(max-width: 767px)")` on top of `settings.sidebarCollapsed`, and exposes a `toggle` that no-ops when the viewport is forcing the collapse.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/useSidebarCollapsed.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSidebarCollapsed } from "@/hooks/useSidebarCollapsed";

// --- matchMedia mock helpers ---

type Listener = (e: { matches: boolean }) => void;

interface FakeMediaQueryList {
  matches: boolean;
  addEventListener: (type: "change", fn: Listener) => void;
  removeEventListener: (type: "change", fn: Listener) => void;
  dispatchChange: (matches: boolean) => void;
  // Legacy API stubs for compatibility.
  addListener: (fn: Listener) => void;
  removeListener: (fn: Listener) => void;
  media: string;
  onchange: null;
}

let mqls: FakeMediaQueryList[] = [];

function fakeMatchMedia(query: string): FakeMediaQueryList {
  const listeners = new Set<Listener>();
  const mql: FakeMediaQueryList = {
    matches: false,
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
}

beforeEach(() => {
  localStorage.clear();
  mqls = [];
  vi.stubGlobal("matchMedia", fakeMatchMedia);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSidebarCollapsed", () => {
  it("defaults to collapsed=false when nothing is set", () => {
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current.collapsed).toBe(false);
    expect(result.current.forceCollapsedByViewport).toBe(false);
  });

  it("toggle() flips the persisted setting", () => {
    const { result } = renderHook(() => useSidebarCollapsed());
    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(true);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.sidebarCollapsed).toBe(true);
  });

  it("viewport match forces collapsed=true even when setting is false", () => {
    // Pre-seed matchMedia to match before the hook mounts.
    const original = fakeMatchMedia;
    vi.stubGlobal("matchMedia", (q: string) => {
      const mql = original(q);
      if (q.includes("max-width: 767px")) mql.matches = true;
      return mql;
    });

    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current.collapsed).toBe(true);
    expect(result.current.forceCollapsedByViewport).toBe(true);
  });

  it("matchMedia change event updates collapsed live", () => {
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current.collapsed).toBe(false);

    // Find the mql the hook subscribed to and dispatch a change.
    const mql = mqls.find((m) => m.media.includes("max-width: 767px"));
    expect(mql).toBeDefined();
    act(() => mql!.dispatchChange(true));

    expect(result.current.forceCollapsedByViewport).toBe(true);
    expect(result.current.collapsed).toBe(true);
  });

  it("toggle() is a no-op when the viewport is forcing collapse", () => {
    vi.stubGlobal("matchMedia", (q: string) => {
      const mql = fakeMatchMedia(q);
      if (q.includes("max-width: 767px")) mql.matches = true;
      return mql;
    });

    const { result } = renderHook(() => useSidebarCollapsed());
    act(() => result.current.toggle());

    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    // Setting must not have been touched.
    expect(stored.sidebarCollapsed ?? false).toBe(false);
    // Effective state is still forced collapsed.
    expect(result.current.collapsed).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useSidebarCollapsed.test.ts
```

Expected: FAIL with a module-resolution error on `@/hooks/useSidebarCollapsed` — the file doesn't exist yet.

- [ ] **Step 3: Implement the hook**

Create `web/src/hooks/useSidebarCollapsed.ts`:

```ts
import { useCallback, useEffect, useState } from "react";
import { useSettings } from "./useSettings";

const QUERY = "(max-width: 767px)";

function getInitialMatch(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(QUERY).matches;
}

export interface UseSidebarCollapsedResult {
  collapsed: boolean;
  toggle: () => void;
  forceCollapsedByViewport: boolean;
}

export function useSidebarCollapsed(): UseSidebarCollapsedResult {
  const { settings, update } = useSettings();
  const [forceCollapsedByViewport, setForced] = useState<boolean>(getInitialMatch);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(QUERY);
    // Re-read in case the media query changed between module init and mount.
    setForced(mql.matches);
    const onChange = (e: MediaQueryListEvent | { matches: boolean }) => {
      setForced(e.matches);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    if (forceCollapsedByViewport) return;
    update({ sidebarCollapsed: !settings.sidebarCollapsed });
  }, [forceCollapsedByViewport, settings.sidebarCollapsed, update]);

  const collapsed = forceCollapsedByViewport || settings.sidebarCollapsed;
  return { collapsed, toggle, forceCollapsedByViewport };
}
```

- [ ] **Step 4: Run tests and watch them pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/useSidebarCollapsed.test.ts
```

Expected: PASS — 5 tests, 0 failures.

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 48 tests (43 prior + 5 new), 0 failures.

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
git add web/src/hooks/useSidebarCollapsed.ts web/tests/unit/useSidebarCollapsed.test.ts
git commit -m "feat(web): useSidebarCollapsed hook with viewport override"
```

---

## Task 3: Wire the hook into `AppShell` + keyboard shortcut

**Files:**
- Modify: `web/src/AppShell.tsx`

No new unit test in this task — the hook test already covers state logic, and the AppShell changes are glue. The keyboard shortcut will be verified manually in Task 8 (visual check).

- [ ] **Step 1: Update `AppShell` to derive the grid template**

Replace the entire contents of `web/src/AppShell.tsx` with:

```tsx
import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { useApplyTheme } from "./hooks/useApplyTheme";
import { useSidebarCollapsed } from "./hooks/useSidebarCollapsed";

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
  const { collapsed, toggle, forceCollapsedByViewport } = useSidebarCollapsed();

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

  const gridCols = collapsed ? "grid-cols-[48px_1fr]" : "grid-cols-[180px_1fr]";

  return (
    <div className={`min-h-screen grid ${gridCols} bg-bg text-text font-sans`}>
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

Expected: PASS — all 48 tests still pass. `AppShell` isn't covered by any existing test.

- [ ] **Step 4: Commit**

```bash
cd <worktree>
git add web/src/AppShell.tsx
git commit -m "feat(web): AppShell reacts to sidebar-collapse + Cmd/Ctrl+B shortcut"
```

---

## Task 4: Refactor `Sidebar` Item to take `glyph` + `label` as separate props

**Files:**
- Modify: `web/src/components/Sidebar.tsx`
- Create: `web/tests/unit/Sidebar.test.tsx`

Pure refactor — no visual change yet. Establishes the Item API that Task 5 needs. Lock the nav list with a new unit test so subsequent refactors can't silently drop items.

- [ ] **Step 1: Write failing tests that reflect the expected rendered output**

Create `web/tests/unit/Sidebar.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { Sidebar } from "@/components/Sidebar";

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  it("renders all five workspace nav links with their labels", () => {
    renderSidebar();
    for (const label of ["scan", "snapshots", "history", "providers", "settings"]) {
      expect(screen.getByRole("link", { name: new RegExp(label, "i") })).toBeInTheDocument();
    }
  });

  it("each nav link renders its glyph", () => {
    renderSidebar();
    const expected = [
      { label: "scan", glyph: "◆" },
      { label: "snapshots", glyph: "⏱" },
      { label: "history", glyph: "≡" },
      { label: "providers", glyph: "⚙" },
      { label: "settings", glyph: "⚡" },
    ];
    for (const { label, glyph } of expected) {
      const link = screen.getByRole("link", { name: new RegExp(label, "i") });
      expect(link.textContent).toContain(glyph);
    }
  });
});
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: FAIL — the test assertions aren't quite matching the current format. The current labels include the glyph inline (e.g. `"◆ scan"`), so the `name` regex `/scan/i` DOES match and `textContent` DOES contain `◆`. Both tests likely PASS today without any source change. That's fine — it proves the tests are correctly pinning the pre-refactor behaviour. Expect **2 tests, 0 failures**.

If the tests fail instead, read the output carefully — the label strings are `"◆ scan"` etc. with a space separator; the regex `/scan/i` should still match.

- [ ] **Step 3: Refactor `Sidebar.tsx` Item component**

Replace the entire contents of `web/src/components/Sidebar.tsx` with:

```tsx
import { NavLink } from "react-router-dom";

const linkBase =
  "flex justify-between items-center px-3 py-1.5 rounded text-[10.5px] font-mono transition-colors";
const linkActive = "bg-bg-elev-2 text-text";
const linkIdle = "text-text-dim hover:bg-bg-elev-1";

function Item({
  to,
  glyph,
  label,
  count,
}: {
  to: string;
  glyph: string;
  label: string;
  count?: number;
}) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) => `${linkBase} ${isActive ? linkActive : linkIdle}`}
    >
      <span>
        <span aria-hidden="true">{glyph}</span> {label}
      </span>
      {count !== undefined && <span className="text-text-muted text-[9.5px]">{count}</span>}
    </NavLink>
  );
}

export function Sidebar() {
  return (
    <aside className="bg-bg-elev-1 border-r border-border p-3 sticky top-0 h-screen">
      <div className="flex gap-2 items-center pb-3 mb-4 border-b border-border">
        <span
          className="w-[7px] h-[7px] rounded-full bg-risk-reclaim"
          style={{ boxShadow: "0 0 10px var(--risk-reclaim)" }}
        />
        <span className="font-mono font-semibold text-[12px]">diskdoctor</span>
      </div>
      <div className="text-text-muted text-[9px] uppercase tracking-widest px-2 pb-1">
        workspace
      </div>
      <nav className="flex flex-col gap-0.5 mb-4">
        <Item to="/" glyph="◆" label="scan" />
        <Item to="/snapshots" glyph="⏱" label="snapshots" />
        <Item to="/history" glyph="≡" label="history" />
        <Item to="/providers" glyph="⚙" label="providers" />
        <Item to="/settings" glyph="⚡" label="settings" />
      </nav>
    </aside>
  );
}
```

The visual output is identical to before the refactor: `<span>[glyph] [label]</span>`. The glyph is `aria-hidden="true"` so screen readers announce only the text label — a small accessibility improvement on top of the refactor.

- [ ] **Step 4: Run the Sidebar tests**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: PASS — 2 tests.

- [ ] **Step 5: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 50 tests (48 prior + 2 new).

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/components/Sidebar.tsx web/tests/unit/Sidebar.test.tsx
git commit -m "refactor(web): split Sidebar Item into glyph + label props"
```

---

## Task 5: Sidebar collapsed rendering (TDD)

**Files:**
- Modify: `web/src/components/Sidebar.tsx`
- Modify: `web/tests/unit/Sidebar.test.tsx`

Wire in `useSidebarCollapsed`. When collapsed: label becomes `sr-only`, the link gets a native `title` tooltip, the `workspace` section header is hidden, the row centers its glyph.

- [ ] **Step 1: Add failing collapsed-mode tests**

In `web/tests/unit/Sidebar.test.tsx`, add the imports for act/localStorage control at the top if not already present (the existing imports only need `MemoryRouter`, `render`, `screen`, `describe`, `it`, `expect`; no new top-level imports required).

Append to the `describe("Sidebar", ...)` block:

```tsx
  describe("when collapsed", () => {
    beforeEach(() => {
      localStorage.clear();
      localStorage.setItem(
        "diskdoctor.settings.v1",
        JSON.stringify({ sidebarCollapsed: true }),
      );
    });

    it("hides the workspace section header", () => {
      renderSidebar();
      expect(screen.queryByText(/^workspace$/i)).not.toBeInTheDocument();
    });

    it("each nav link has its full label text marked sr-only", () => {
      renderSidebar();
      const scanLink = screen.getByRole("link", { name: /scan/i });
      const label = scanLink.querySelector(".sr-only");
      expect(label).not.toBeNull();
      expect(label?.textContent).toBe("scan");
    });

    it("each nav link carries a title attribute equal to its label", () => {
      renderSidebar();
      const expected = [
        ["/", "scan"],
        ["/snapshots", "snapshots"],
        ["/history", "history"],
        ["/providers", "providers"],
        ["/settings", "settings"],
      ] as const;
      for (const [href, label] of expected) {
        const link = screen
          .getAllByRole("link")
          .find((l) => l.getAttribute("href") === href);
        expect(link).toBeDefined();
        expect(link?.getAttribute("title")).toBe(label);
      }
    });
  });
```

Also add `beforeEach` to the top-level imports from vitest:

```tsx
import { describe, it, expect, beforeEach } from "vitest";
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: FAIL — three new tests fail because the Sidebar doesn't yet react to the setting.

- [ ] **Step 3: Update `Sidebar.tsx` to consume `useSidebarCollapsed`**

Replace the entire contents of `web/src/components/Sidebar.tsx` with:

```tsx
import { NavLink } from "react-router-dom";
import { useSidebarCollapsed } from "@/hooks/useSidebarCollapsed";

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

export function Sidebar() {
  const { collapsed } = useSidebarCollapsed();
  return (
    <aside className="bg-bg-elev-1 border-r border-border p-3 sticky top-0 h-screen">
      <div
        className={`flex gap-2 items-center pb-3 mb-4 border-b border-border ${
          collapsed ? "justify-center" : ""
        }`}
      >
        <span
          className="w-[7px] h-[7px] rounded-full bg-risk-reclaim"
          style={{ boxShadow: "0 0 10px var(--risk-reclaim)" }}
        />
        {!collapsed && (
          <span className="font-mono font-semibold text-[12px]">diskdoctor</span>
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
    </aside>
  );
}
```

- [ ] **Step 4: Run tests and watch them pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: PASS — 5 tests (2 expanded + 3 collapsed).

- [ ] **Step 5: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 53 tests.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/components/Sidebar.tsx web/tests/unit/Sidebar.test.tsx
git commit -m "feat(web): Sidebar renders collapsed icons-only mode"
```

---

## Task 6: Chevron toggle inside the Sidebar (TDD)

**Files:**
- Modify: `web/src/components/Sidebar.tsx`
- Modify: `web/tests/unit/Sidebar.test.tsx`

- [ ] **Step 1: Add failing tests for the chevron**

Append to the top-level `describe("Sidebar", ...)` block (NOT inside the `when collapsed` sub-describe):

```tsx
  it("renders a chevron toggle with aria-expanded=true when expanded", () => {
    renderSidebar();
    const btn = screen.getByRole("button", { name: /collapse sidebar/i });
    expect(btn).toBeInTheDocument();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });
```

Then append this inside the existing `describe("when collapsed", ...)` block:

```tsx
    it("renders a chevron toggle with aria-expanded=false when collapsed", () => {
      renderSidebar();
      const btn = screen.getByRole("button", { name: /expand sidebar/i });
      expect(btn).toBeInTheDocument();
      expect(btn.getAttribute("aria-expanded")).toBe("false");
    });
```

Also add a new sub-describe after `when collapsed`:

```tsx
  describe("when the viewport forces collapsed", () => {
    beforeEach(() => {
      localStorage.clear();
      // Force matchMedia to match so useSidebarCollapsed sees
      // forceCollapsedByViewport=true.
      const realMatchMedia = window.matchMedia;
      window.matchMedia = ((query: string) => {
        const mql = realMatchMedia.call(window, query);
        return new Proxy(mql, {
          get(t, p) {
            if (p === "matches" && typeof query === "string" && query.includes("max-width: 767px")) {
              return true;
            }
            const v = (t as unknown as Record<PropertyKey, unknown>)[p];
            return typeof v === "function" ? v.bind(t) : v;
          },
        });
      }) as typeof window.matchMedia;
    });

    it("does not render the chevron button", () => {
      renderSidebar();
      expect(
        screen.queryByRole("button", { name: /(collapse|expand) sidebar/i }),
      ).not.toBeInTheDocument();
    });
  });
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: FAIL on the three new assertions — no chevron button exists yet.

- [ ] **Step 3: Add the chevron to `Sidebar.tsx`**

Replace the entire contents of `web/src/components/Sidebar.tsx` with:

```tsx
import { NavLink } from "react-router-dom";
import { useSidebarCollapsed } from "@/hooks/useSidebarCollapsed";

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
  const { collapsed, toggle, forceCollapsedByViewport } = useSidebarCollapsed();
  return (
    <aside className="bg-bg-elev-1 border-r border-border p-3 sticky top-0 h-screen">
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
    </aside>
  );
}
```

Layout summary: when expanded, the brand row is `[dot diskdoctor] [flex-1 spacer] [◀]`. When collapsed, the same row stacks vertically: `[dot]` above `[▶]`, both centered. When force-collapsed, the `ChevronToggle` is simply not rendered.

- [ ] **Step 4: Run Sidebar tests**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/Sidebar.test.tsx
```

Expected: PASS — 8 tests in the file (3 top-level + 4 collapsed + 1 force-collapsed).

- [ ] **Step 5: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 56 tests total (53 prior + 3 new: the two chevron tests plus the force-collapsed one). If the count is a little off but all tests pass and the new assertions are green, that's fine — what matters is no regressions.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/components/Sidebar.tsx web/tests/unit/Sidebar.test.tsx
git commit -m "feat(web): chevron toggle in Sidebar with viewport override"
```

---

## Task 7: Settings page entry

**Files:**
- Modify: `web/src/pages/Settings.tsx`

The Settings page doesn't have a test file today. The plan's spec explicitly calls this out; adding test scaffolding for a single chip pair is overkill. Manual verification in Task 8.

- [ ] **Step 1: Add a Sidebar section between Appearance and Minimum size cutoff**

Open `web/src/pages/Settings.tsx`. Find the `Section` for "Appearance" (near line 80). Immediately AFTER its closing `</Section>` and BEFORE the `<Section title="Minimum size cutoff" ...>` opening tag, insert:

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

This uses the existing `applyAndFlash` helper (which triggers the "● saved" chip) and the existing `Chip` / `Section` components. No other changes needed.

- [ ] **Step 2: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS. Since we added `sidebarCollapsed: boolean` to the `Settings` type in Task 1, `applyAndFlash({ sidebarCollapsed: ... })` typechecks correctly.

- [ ] **Step 3: Run the full suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — no test changes, no regressions.

- [ ] **Step 4: Commit**

```bash
cd <worktree>
git add web/src/pages/Settings.tsx
git commit -m "feat(web): Settings page sidebar expanded/collapsed chips"
```

---

## Task 8: Build, visual check, keyboard-shortcut verification

- [ ] **Step 1: Production build**

Run:
```bash
cd <worktree>/web
npm run build
```

Expected: clean build, no TypeScript errors, bundle size roughly unchanged (hook + small JSX additions are sub-kilobyte).

- [ ] **Step 2: Full test sweep**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: ALL PASS. 56 tests total (43 baseline + 5 useSidebarCollapsed + 8 Sidebar).

- [ ] **Step 3: Dev server + manual check**

Run:
```bash
cd <worktree>/web
npm run dev
```

Verify in the browser:

1. **Default state:** Sidebar is expanded (180px). All five nav items show glyph + label.
2. **Click chevron (◀) in the sidebar brand row:** Sidebar collapses to 48px, only colored dot + glyphs remain. Chevron becomes ▶ centered below the dot.
3. **Hover a nav item in collapsed mode:** native tooltip appears showing the full label.
4. **Cmd+B on macOS (or Ctrl+B on Linux/Windows):** Toggles between expanded and collapsed. Test with focus NOT in any input field.
5. **Cmd/Ctrl+B while focused in a text input** (e.g. the search box on Providers page): DOES NOT toggle; the shortcut is ignored and the browser's default behaviour (or no-op) applies.
6. **Resize the window below 768px:** Sidebar force-collapses. Chevron disappears. Cmd/Ctrl+B becomes a no-op (nothing happens on press).
7. **Resize back above 768px:** Sidebar returns to the setting's state (expanded if the setting is false). Chevron reappears.
8. **Navigate to Settings page:** The new "Sidebar" section sits between "Appearance" and "Minimum size cutoff". Chips `[expanded]` `[collapsed]` reflect the current setting. Click toggles it, "● saved" flashes, sidebar updates live.
9. **Reload the page with a chosen state:** The state persists (localStorage).
10. **Reset to defaults on Settings page:** Sidebar returns to expanded.

- [ ] **Step 4: Confirm no regressions in other UI**

Spot-check:
- Scan page loads, provider icons still render correctly.
- Cleanup wizard still opens and advances.
- Theme toggle still works.
- Provider enable/disable toggles still work.

- [ ] **Step 5: Final commit (only if touch-ups happened in this task)**

If no changes, skip. Otherwise stage and commit any touch-ups.

---

## Out of scope

- Animation on collapse/expand. The grid snaps in one frame.
- "Peek on hover" when collapsed. Tooltip only.
- Per-route sidebar state. Global setting.
- Remembering different states for different viewports.
- Changes to other navigation or chrome (top bar, DiskUsageBar, etc.).

## Rollback

Every commit is self-contained and reverse-ordered can roll back the feature step-by-step:

```bash
cd <worktree>
git log --oneline | grep -E "(sidebar|Sidebar|AppShell reacts|sidebarCollapsed)" | awk '{print $1}'
# git revert each in reverse order
```

No data migration, no stored-state incompatibility (the new `sidebarCollapsed` field is defaulted at read time, so pre-feature localStorage entries continue to load).
