import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: width,
  });
}

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
  // Default the viewport to "narrow" (< 1280) so legacy assertions about
  // owner/perms-hidden hold without each test having to set it.
  setViewportWidth(1024);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useHiddenColumns", () => {
  it("defaults match the column registry's defaultVisible flags (owner/perms hidden)", async () => {
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    expect(result.current.isVisible("provider")).toBe(true);
    expect(result.current.isVisible("size")).toBe(true);
    expect(result.current.isVisible("risk")).toBe(true);
    expect(result.current.isVisible("stale")).toBe(true);
    expect(result.current.isVisible("owner")).toBe(false);
    expect(result.current.isVisible("perms")).toBe(false);
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
      JSON.stringify({
        scanTableHiddenColumns: ["stale"],
        scanTableColumnsCustomized: true,
      }),
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
      JSON.stringify({
        scanTableHiddenColumns: ["stale", "unknown_column", "owner"],
        scanTableColumnsCustomized: true,
      }),
    );
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    expect(result.current.isVisible("stale")).toBe(false);
    expect(result.current.isVisible("owner")).toBe(false);
    expect(result.current.isVisible("size")).toBe(true);
  });

  it("auto-shows owner/perms on wide viewports when the user hasn't customized", async () => {
    setViewportWidth(1600);
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    expect(result.current.isVisible("owner")).toBe(true);
    expect(result.current.isVisible("perms")).toBe(true);
  });

  it("respects the user's explicit choice over the viewport default once customized", async () => {
    setViewportWidth(1600);
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({
        scanTableHiddenColumns: ["owner", "perms"],
        scanTableColumnsCustomized: true,
      }),
    );
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    // Wide viewport would auto-show, but the user said no.
    expect(result.current.isVisible("owner")).toBe(false);
    expect(result.current.isVisible("perms")).toBe(false);
  });

  it("setHidden flips scanTableColumnsCustomized to true so the picker overrides viewport defaults", async () => {
    setViewportWidth(1600);
    const { useHiddenColumns } = await import("@/hooks/useHiddenColumns");
    const { result } = renderHook(() => useHiddenColumns());
    expect(result.current.isVisible("owner")).toBe(true); // wide → auto-shown
    act(() => result.current.setHidden("owner", true));
    expect(result.current.isVisible("owner")).toBe(false);
    const stored = JSON.parse(localStorage.getItem("diskdoctor.settings.v1") ?? "{}");
    expect(stored.scanTableColumnsCustomized).toBe(true);
    expect(stored.scanTableHiddenColumns).toContain("owner");
  });
});
