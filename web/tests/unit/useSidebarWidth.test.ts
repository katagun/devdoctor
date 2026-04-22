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
