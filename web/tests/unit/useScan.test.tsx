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
});
