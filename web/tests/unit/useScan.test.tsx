import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const mockApiFetch = vi.fn();

vi.mock("@/api", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function entry(
  id: string,
  size: number,
  risk: "safe" | "reclaimable" | "dangerous",
) {
  return {
    id,
    provider: id,
    label: id,
    path: `/x/${id}`,
    size_bytes: size,
    mtime: 0,
    risk,
    recipe: ["rm"],
  };
}

beforeEach(() => {
  mockApiFetch.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useScan", () => {
  it("excludes dangerous entries from totalBytes (the headline 'reclaimable' figure)", async () => {
    mockApiFetch.mockResolvedValue({
      entries: [
        entry("a-safe", 1000, "safe"),
        entry("b-reclaim", 500, "reclaimable"),
        entry("c-danger", 9999, "dangerous"),
      ],
      scanned_at: "2026-04-25T10:00:00Z",
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { useScan } = await import("@/hooks/useScan");
    const { result } = renderHook(() => useScan(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(result.current.data?.totalBytes).toBe(1500);
    // Rows still include the danger entry — only the headline metric drops it.
    expect(result.current.data?.rows.length).toBe(3);
  });

  it("keeps an unmeasured footprint as null instead of substituting size_bytes", async () => {
    mockApiFetch.mockResolvedValue({
      entries: [
        { ...entry("worktree", 0, "dangerous"), footprint_bytes: null, reclaimable_bytes: null },
        { ...entry("measured", 700, "safe"), footprint_bytes: 700, reclaimable_bytes: 700 },
        entry("legacy", 300, "safe"),
      ],
      scanned_at: "2026-04-25T10:00:00Z",
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { useScan } = await import("@/hooks/useScan");
    const { result } = renderHook(() => useScan(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    const byId = Object.fromEntries(result.current.data!.rows.map((r) => [r.id, r]));
    expect(byId.worktree.footprint_bytes).toBeNull();
    expect(byId.worktree.size_bytes).toBe(0);
    expect(byId.worktree.reclaimable_bytes).toBeNull();
    expect(byId.measured.footprint_bytes).toBe(700);
    expect(byId.legacy.footprint_bytes).toBe(300);
  });

  it("returns 0 totalBytes when every entry is dangerous", async () => {
    mockApiFetch.mockResolvedValue({
      entries: [entry("a", 1000, "dangerous"), entry("b", 2000, "dangerous")],
      scanned_at: "2026-04-25T10:00:00Z",
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { useScan } = await import("@/hooks/useScan");
    const { result } = renderHook(() => useScan(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(result.current.data?.totalBytes).toBe(0);
  });

  it("passes provider filters through to the scan API", async () => {
    mockApiFetch.mockResolvedValue({
      entries: [],
      scanned_at: "2026-04-25T10:00:00Z",
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { useScan } = await import("@/hooks/useScan");
    const { result } = renderHook(() => useScan({ provider: "docker-vm-disk" }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.data).toBeTruthy());

    expect(mockApiFetch).toHaveBeenCalledWith(
      "/scan?provider=docker-vm-disk&snapshot=true&snapshot_min_interval_ms=300000",
    );
  });

  it("asks every scan for an auto-snapshot, rate-limited by the cadence", async () => {
    // Dashboard and Disk share one query, so neither may be the "implicit" one
    // that skips the snapshot; the server's interval check keeps the cadence.
    mockApiFetch.mockResolvedValue({
      entries: [],
      scanned_at: "2026-04-25T10:00:00Z",
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { useScan } = await import("@/hooks/useScan");
    const { result } = renderHook(() => useScan({ snapshotMinIntervalMs: 3_600_000 }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.data).toBeTruthy());

    expect(mockApiFetch).toHaveBeenCalledWith(
      "/scan?snapshot=true&snapshot_min_interval_ms=3600000",
    );
  });

  it("never asks for auto-snapshots more often than every five minutes", async () => {
    // The "live" cadence has a zero staleTime; without a floor every page mount
    // and refresh would write a snapshot and fill the history with minutes.
    mockApiFetch.mockResolvedValue({
      entries: [],
      scanned_at: "2026-04-25T10:00:00Z",
      hostname: "h",
      platform: "darwin",
      skipped_paths: [],
    });
    const { useScan } = await import("@/hooks/useScan");
    const { result } = renderHook(() => useScan({ snapshotMinIntervalMs: 0 }), { wrapper });

    await waitFor(() => expect(result.current.data).toBeTruthy());

    expect(mockApiFetch).toHaveBeenCalledWith(
      "/scan?snapshot=true&snapshot_min_interval_ms=300000",
    );
  });
});
