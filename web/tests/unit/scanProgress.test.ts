import { describe, expect, it } from "vitest";
import { formatScanProgress, type ScanProgressSnapshot } from "@/lib/scanProgress";

function snapshot(over: Partial<ScanProgressSnapshot> = {}): ScanProgressSnapshot {
  return {
    scan_id: 1,
    status: "running",
    started_at: "2026-09-15T10:00:00+00:00",
    total: 22,
    done: 12,
    running: ["xcode-development-data", "docker"],
    entries: 340,
    bytes: 45_200_000_000,
    providers: [],
    ...over,
  };
}

describe("formatScanProgress", () => {
  it("names the provider count, bytes found and the running providers", () => {
    const parts = formatScanProgress(snapshot());
    expect(parts.providers).toBe("12/22 providers");
    expect(parts.found).toBe("42.1G found");
    expect(parts.running).toBe("running: xcode-development-data, docker");
    expect(parts.finishing).toBe(false);
  });

  it("omits 'found' until a provider has finished, even at zero bytes", () => {
    expect(formatScanProgress(snapshot({ done: 0, bytes: 0 })).found).toBeNull();
    expect(formatScanProgress(snapshot({ done: 1, bytes: 0 })).found).toBe("0B found");
  });

  it("omits 'running' when nothing is running and caps the names at three", () => {
    expect(formatScanProgress(snapshot({ running: [] })).running).toBeNull();
    expect(formatScanProgress(snapshot({ running: ["a", "b", "c", "d", "e"] })).running).toBe(
      "running: a, b, c +2",
    );
  });

  it("flags finishing once every provider is done", () => {
    const parts = formatScanProgress(snapshot({ status: "done", done: 22, running: [] }));
    expect(parts.finishing).toBe(true);
    expect(parts.providers).toBe("22/22 providers");
  });
});
