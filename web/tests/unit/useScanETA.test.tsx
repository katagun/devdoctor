import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const mockApiFetch = vi.fn();

vi.mock("@/api", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

vi.mock("@/hooks/useSelectedProviders", () => ({
  useSelectedProviders: () => ({
    isEnabled: (name: string) => mockEnabledProviders.has(name),
  }),
}));

let mockEnabledProviders = new Set<string>();

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockApiFetch.mockReset();
  mockEnabledProviders = new Set(["ollama", "hf", "docker"]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useScanETA", () => {
  it("returns null etaMs with fewer than 3 samples", async () => {
    mockApiFetch.mockResolvedValue([]);
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    await waitFor(() => expect(result.current).toBeTruthy());
    expect(result.current.etaMs).toBeNull();
    expect(result.current.sampleSize).toBe(0);
  });

  it("sums medians across enabled providers only", async () => {
    const fake = [
      {
        name: "a", path: "a", scanned_at: "2026-04-24T12:00:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 500 },
        ],
      },
      {
        name: "b", path: "b", scanned_at: "2026-04-24T12:01:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 2000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 300 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 400 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 700 },
        ],
      },
      {
        name: "c", path: "c", scanned_at: "2026-04-24T12:02:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1500,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 200 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 300 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 600 },
        ],
      },
    ];
    mockApiFetch.mockResolvedValue(fake);
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    await waitFor(() => expect(result.current.etaMs).not.toBeNull());
    // Medians: ollama=200, hf=300, docker=600. Sum=1100.
    expect(result.current.etaMs).toBe(1100);
    expect(result.current.providerCount).toBe(3);
    expect(result.current.sampleSize).toBe(3);
  });

  it("excludes disabled providers from the sum", async () => {
    mockEnabledProviders = new Set(["ollama", "hf"]);
    const fake = [
      {
        name: "a", path: "a", scanned_at: "2026-04-24T12:00:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 5000 },
        ],
      },
      {
        name: "b", path: "b", scanned_at: "2026-04-24T12:01:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 2000,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 5000 },
        ],
      },
      {
        name: "c", path: "c", scanned_at: "2026-04-24T12:02:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 1500,
        per_provider: [
          { name: "ollama", bytes: 0, entries: 0, duration_ms: 100 },
          { name: "hf",     bytes: 0, entries: 0, duration_ms: 200 },
          { name: "docker", bytes: 0, entries: 0, duration_ms: 5000 },
        ],
      },
    ];
    mockApiFetch.mockResolvedValue(fake);
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    await waitFor(() => expect(result.current.etaMs).not.toBeNull());
    // docker excluded: median(100) + median(200) = 300.
    expect(result.current.etaMs).toBe(300);
    expect(result.current.providerCount).toBe(2);
  });

  it("filters out snapshots with null/missing duration_ms", async () => {
    const fake = [
      {
        name: "a", path: "a", scanned_at: "2026-04-24T12:00:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: null, per_provider: [],
      },
      {
        name: "b", path: "b", scanned_at: "2026-04-24T12:01:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 500,
        per_provider: [{ name: "ollama", bytes: 0, entries: 0, duration_ms: 100 }],
      },
      {
        name: "c", path: "c", scanned_at: "2026-04-24T12:02:00Z",
        hostname: "h", platform: "darwin", note: null, total_bytes: 0,
        kind: "auto", duration_ms: 600,
        per_provider: [{ name: "ollama", bytes: 0, entries: 0, duration_ms: 200 }],
      },
    ];
    mockApiFetch.mockResolvedValue(fake);
    const { useScanETA } = await import("@/hooks/useScanETA");
    const { result } = renderHook(() => useScanETA(), { wrapper });
    await waitFor(() => expect(result.current).toBeTruthy());
    // Only 2 usable samples; < 3 threshold → etaMs null.
    expect(result.current.etaMs).toBeNull();
    expect(result.current.sampleSize).toBe(2);
  });
});
