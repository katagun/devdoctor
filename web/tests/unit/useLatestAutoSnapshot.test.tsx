import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiFetchMock = vi.fn();
vi.mock("@/api", () => ({
  apiFetch: (path: string) => apiFetchMock(path),
}));

import { useLatestAutoSnapshot } from "@/hooks/useSnapshots";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useLatestAutoSnapshot", () => {
  beforeEach(() => apiFetchMock.mockReset());

  it("requests the newest auto snapshot and returns the single meta", async () => {
    apiFetchMock.mockResolvedValue([
      {
        name: "2026-04-24--auto.json",
        path: "/x/a.json",
        scanned_at: "2026-04-24T00:00:00Z",
        hostname: "h",
        platform: "darwin",
        note: null,
        total_bytes: 100,
        kind: "auto",
        duration_ms: 1234,
        entry_count: 10,
        per_provider: [{ name: "ollama", bytes: 100, entries: 1, duration_ms: 50 }],
      },
    ]);

    const { result } = renderHook(() => useLatestAutoSnapshot(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(apiFetchMock).toHaveBeenCalledWith("/snapshots?kind=auto&limit=1");
    expect(result.current.data?.duration_ms).toBe(1234);
  });

  it("returns null when no auto snapshots exist", async () => {
    apiFetchMock.mockResolvedValue([]);

    const { result } = renderHook(() => useLatestAutoSnapshot(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBeNull();
  });
});
