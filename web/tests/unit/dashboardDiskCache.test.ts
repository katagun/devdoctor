import { beforeEach, describe, expect, it } from "vitest";
import {
  readDashboardDiskCache,
  writeDashboardDiskCache,
} from "@/lib/dashboardDiskCache";

describe("dashboard disk cache", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("round-trips cache rows for the same provider scope", () => {
    writeDashboardDiskCache({
      scannedAt: "2026-05-05T10:00:00Z",
      totalBytes: 123,
      providerParam: "docker,ollama",
      rows: [
        {
          id: "docker:a",
          provider: "docker",
          label: "a",
          size_bytes: 123,
          risk: "reclaimable",
        },
      ],
    });

    expect(readDashboardDiskCache("docker,ollama")).toEqual({
      scannedAt: "2026-05-05T10:00:00Z",
      totalBytes: 123,
      providerParam: "docker,ollama",
      rows: [
        {
          id: "docker:a",
          provider: "docker",
          label: "a",
          size_bytes: 123,
          risk: "reclaimable",
        },
      ],
    });
  });

  it("ignores cache rows for a different provider scope", () => {
    writeDashboardDiskCache({
      scannedAt: "2026-05-05T10:00:00Z",
      totalBytes: 123,
      providerParam: null,
      rows: [],
    });

    expect(readDashboardDiskCache("docker")).toBeNull();
  });

  it("ignores malformed cache payloads", () => {
    localStorage.setItem("devdoctor.dashboard.disk.v1", JSON.stringify({ rows: "bad" }));

    expect(readDashboardDiskCache(undefined)).toBeNull();
  });
});
