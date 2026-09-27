import { describe, expect, it } from "vitest";
import { diskScanReady } from "@/lib/providerFilters";

describe("diskScanReady", () => {
  it("is ready at once when nothing is disabled: the filter never depends on the list", () => {
    expect(diskScanReady(undefined, new Set())).toBe(true);
  });

  it("waits for the provider list when some are disabled", () => {
    expect(diskScanReady(undefined, new Set(["docker"]))).toBe(false);
  });

  it("is ready once the list has loaded", () => {
    expect(diskScanReady([{ name: "docker" }, { name: "uv-cache" }], new Set(["docker"]))).toBe(true);
  });

  it("opens when the provider list failed to load, so the page falls back to an unfiltered scan", () => {
    expect(diskScanReady(undefined, new Set(["docker"]), true)).toBe(true);
    expect(diskScanReady(undefined, new Set(["docker"]), false)).toBe(false);
  });
});
