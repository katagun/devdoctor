import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { postJson } = vi.hoisted(() => ({ postJson: vi.fn() }));
vi.mock("@/api", () => ({
  apiFetch: (url: string, init?: RequestInit) => {
    postJson(url, init?.body);
    if (url === "/clean/jobs") return Promise.resolve({ job_id: "job-1" });
    return Promise.resolve({});
  },
  ApiError: class ApiError extends Error {},
}));

// Fake EventSource (same shape as the useSSE test).
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, Array<(e: MessageEvent) => void>> = {};
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  removeEventListener() {}
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    for (const fn of this.listeners[type] ?? [])
      fn(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}

import { useCleanupWizard } from "@/hooks/useCleanupWizard";

beforeEach(() => {
  postJson.mockReset();
  FakeEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof FakeEventSource }).EventSource =
    FakeEventSource;
});

describe("useCleanupWizard", () => {
  it("drives through prompt → confirm → done", async () => {
    const entries = [
      {
        id: "1",
        provider: "p",
        label: "l",
        path: "/x",
        size_bytes: 100,
        risk: "safe" as const,
        mtime: null,
        recipeHint: "",
      },
    ];
    const qc = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useCleanupWizard({ entries }), { wrapper });

    await act(async () => {
      await result.current.startJob();
    });

    await waitFor(() => expect(result.current.state.jobId).toBe("job-1"));

    const es = FakeEventSource.instances[0];
    act(() => es.emit("prompt", { entry_id: "1", recipe: ["rm /x"] }));
    await waitFor(() =>
      expect(result.current.state.pendingPrompts).toHaveLength(1),
    );

    await act(async () => {
      await result.current.answerPrompt("1", "y");
    });
    await waitFor(() =>
      expect(postJson).toHaveBeenCalledWith(
        "/clean/jobs/job-1/answer",
        expect.any(String),
      ),
    );

    act(() => es.emit("awaiting_confirm", { summary: "confirm?" }));
    await waitFor(() =>
      expect(result.current.state.awaitingConfirm).not.toBeNull(),
    );

    await act(async () => {
      await result.current.confirm();
    });
    await waitFor(() =>
      expect(postJson).toHaveBeenCalledWith(
        "/clean/jobs/job-1/confirm",
        expect.any(String),
      ),
    );

    act(() =>
      es.emit("execute_start", { entry_id: "1", cmd: "rm /x" }),
    );
    act(() =>
      es.emit("execute_result", {
        entry_id: "1",
        status: "ok",
        freed_bytes: 100,
      }),
    );
    act(() =>
      es.emit("done", {
        results: [{ entry_id: "1", status: "ok", freed_bytes: 100 }],
      }),
    );

    await waitFor(() => expect(result.current.state.step).toBe("summary"));
    expect(result.current.state.results).toEqual([
      { entry_id: "1", status: "ok", freed_bytes: 100 },
    ]);
  });
});
