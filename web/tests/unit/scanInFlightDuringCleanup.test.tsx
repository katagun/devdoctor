// A scan that was already running when a cleanup finishes must not bring back
// the row that cleanup just removed: the `done` listener records the removal
// before the in-flight scan lands, and useScan applies every removal newer
// than the scan's own `started_at` (spec: scan-dedupe §1).
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { scanResponse } = vi.hoisted(() => ({ scanResponse: { resolve: (_: unknown) => {} } }));
vi.mock("@/api", async (importOriginal) => {
  const { ApiError } = await importOriginal<typeof import("@/api")>();
  return {
    apiFetch: (url: string) => {
      if (url === "/clean/jobs") return Promise.resolve({ job_id: "j" });
      if (url.startsWith("/scan")) return new Promise((resolve) => (scanResponse.resolve = resolve));
      return Promise.resolve({});
    },
    ApiError,
  };
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, Array<(e: MessageEvent) => void>> = {};
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  removeEventListener() {}
  close() {}
  emit(type: string, data: unknown) {
    for (const fn of this.listeners[type] ?? []) fn(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}
vi.stubGlobal("EventSource", FakeEventSource);

import { useScan } from "@/hooks/useScan";
import { useCleanupWizard } from "@/hooks/useCleanupWizard";

const GONE = {
  id: "p:/x/gone",
  provider: "p",
  label: "gone",
  path: "/x/gone",
  size_bytes: 100,
  footprint_bytes: 100,
  reclaimable_bytes: 100,
  shared_bytes: 0,
  risk: "safe" as const,
  mtime: null,
  recipeHint: "",
  owner: null,
  group: null,
  perms: null,
};

describe("a scan already in flight when a cleanup finishes", () => {
  it("does not bring back the row the cleanup removed", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const startedAt = new Date(Date.now() - 60_000).toISOString();
    const { result } = renderHook(
      () => ({ scan: useScan(), wizard: useCleanupWizard({ entries: [GONE] }) }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.scan.isFetching).toBe(true));
    await act(async () => {
      await result.current.wizard.startJob();
    });
    act(() =>
      FakeEventSource.instances[0].emit("done", {
        results: [{ entry_id: GONE.id, status: "ok", freed_bytes: 100 }],
      }),
    );
    // The scan began a minute ago and still lists the deleted row.
    await act(async () => {
      scanResponse.resolve({
        entries: [
          { id: GONE.id, provider: "p", label: "gone", path: "/x/gone", size_bytes: 100, mtime: 0, risk: "safe", recipe: ["rm"] },
          { id: "p:/x/kept", provider: "p", label: "kept", path: "/x/kept", size_bytes: 50, mtime: 0, risk: "safe", recipe: ["rm"] },
        ],
        scanned_at: new Date().toISOString(),
        started_at: startedAt,
        hostname: "h",
        platform: "darwin",
        skipped_paths: [],
      });
    });
    await waitFor(() => expect(result.current.scan.data).toBeDefined());
    expect(result.current.scan.data!.rows.map((r) => r.id)).toEqual(["p:/x/kept"]);
  });
});
