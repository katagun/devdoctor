import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
      if (type === "change") {
        listeners.add(fn);
      }
    },
    removeEventListener: (type, fn) => {
      if (type === "change") listeners.delete(fn);
    },
    addListener: (fn) => listeners.add(fn),
    removeListener: (fn) => listeners.delete(fn),
    dispatchChange(matches: boolean) {
      this.matches = matches;
      const event = { matches };
      for (const listener of Array.from(listeners)) {
        listener(event);
      }
    },
  };
  mqls.push(mql);
  return mql;
}

beforeEach(() => {
  localStorage.clear();
  // Reset the useSettings module to reinitialize currentSettings from (now-cleared) localStorage
  vi.resetModules();
  mqls = [];
  vi.stubGlobal("matchMedia", fakeMatchMedia);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSidebarCollapsed", () => {
  it("defaults to collapsed=false when nothing is set", async () => {
    const { useSidebarCollapsed } = await import("@/hooks/useSidebarCollapsed");
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current.collapsed).toBe(false);
    expect(result.current.forceCollapsedByViewport).toBe(false);
  });

  it("toggle() flips the persisted setting", async () => {
    const { useSidebarCollapsed } = await import("@/hooks/useSidebarCollapsed");
    const { result } = renderHook(() => useSidebarCollapsed());
    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(true);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.sidebarCollapsed).toBe(true);
  });

  it("viewport match forces collapsed=true even when setting is false", async () => {
    // Pre-seed matchMedia to match before the hook mounts.
    const original = fakeMatchMedia;
    vi.stubGlobal("matchMedia", (q: string) => {
      const mql = original(q);
      if (q.includes("max-width: 767px")) mql.matches = true;
      return mql;
    });

    const { useSidebarCollapsed } = await import("@/hooks/useSidebarCollapsed");
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current.collapsed).toBe(true);
    expect(result.current.forceCollapsedByViewport).toBe(true);
  });

  it("matchMedia change event updates collapsed live", async () => {
    const { useSidebarCollapsed } = await import("@/hooks/useSidebarCollapsed");
    const { result, rerender } = renderHook(() => useSidebarCollapsed());
    expect(result.current.collapsed).toBe(false);

    // Dispatch to every matching mql — the hook's getInitialMatch creates a
    // throwaway mql during render, so only the useEffect's mql is subscribed.
    const matching = mqls.filter((m) => m.media.includes("max-width: 767px"));
    expect(matching.length).toBeGreaterThan(0);
    act(() => matching.forEach((m) => m.dispatchChange(true)));

    // Trigger a re-render to ensure state updates are reflected
    rerender();

    expect(result.current.forceCollapsedByViewport).toBe(true);
    expect(result.current.collapsed).toBe(true);
  });

  it("toggle() is a no-op when the viewport is forcing collapse", async () => {
    vi.stubGlobal("matchMedia", (q: string) => {
      const mql = fakeMatchMedia(q);
      if (q.includes("max-width: 767px")) mql.matches = true;
      return mql;
    });

    const { useSidebarCollapsed } = await import("@/hooks/useSidebarCollapsed");
    const { result } = renderHook(() => useSidebarCollapsed());
    act(() => result.current.toggle());

    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    // Setting must not have been touched.
    expect(stored.sidebarCollapsed ?? false).toBe(false);
    // Effective state is still forced collapsed.
    expect(result.current.collapsed).toBe(true);
  });
});
