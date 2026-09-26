import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { postJson, startResponse } = vi.hoisted(() => ({
  postJson: vi.fn(),
  // What POST /clean/jobs answers; a test can hold it pending to stand in for the
  // server's re-scan of the selection, or reject it.
  startResponse: vi.fn(),
}));
vi.mock("@/api", async (importOriginal) => {
  const { ApiError } = await importOriginal<typeof import("@/api")>();
  return {
    apiFetch: (url: string, init?: RequestInit) => {
      postJson(url, init?.body);
      if (url === "/clean/jobs") return startResponse();
      return Promise.resolve({});
    },
    ApiError,
  };
});

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

import { ApiError } from "@/api";
import { useCleanupWizard, reducer, initial } from "@/hooks/useCleanupWizard";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const ENTRY = {
  id: "p:/x",
  provider: "p",
  label: "l",
  path: "/x",
  size_bytes: 100,
  risk: "safe" as const,
  mtime: null,
  recipeHint: "",
};

function renderWizard() {
  const qc = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
  return renderHook(() => useCleanupWizard({ entries: [ENTRY] }), { wrapper });
}

const startRequests = () => postJson.mock.calls.filter(([url]) => url === "/clean/jobs");

beforeEach(() => {
  postJson.mockReset();
  startResponse.mockReset();
  startResponse.mockResolvedValue({ job_id: "job-1" });
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

  it("caps console output so a chatty command can't grow state without bound", () => {
    let state = initial([]);
    state = reducer(state, { type: "EXECUTE_START", entry_id: "1", cmd: "docker prune" });
    for (let i = 0; i < 5000; i++) {
      state = reducer(state, { type: "EXECUTE_PROGRESS", entry_id: "1", chunk: `line ${i}` });
    }
    const lines = state.progress["1"].consoleLines;
    expect(lines.length).toBeLessThanOrEqual(200);
    // The tail (what the UI actually renders) is preserved.
    expect(lines[lines.length - 1]).toBe("line 4999");
  });

  it("sends explicit consent when a dangerous entry is enabled", async () => {
    const entries = [
      {
        id: "docker:volume:pgdata",
        provider: "docker",
        label: "docker named volume pgdata",
        path: null,
        size_bytes: 5_000_000_000,
        risk: "dangerous" as const,
        mtime: null,
        recipeHint: "docker volume rm pgdata",
      },
    ];
    const qc = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useCleanupWizard({ entries }), { wrapper });

    expect(result.current.state.enabled.size).toBe(0);
    act(() => {
      result.current.toggleEnabled(entries[0].id, true);
    });

    await act(async () => {
      await result.current.startJob();
    });

    const body = postJson.mock.calls.find(([url]) => url === "/clean/jobs")?.[1];
    expect(JSON.parse(String(body))).toEqual({
      entry_ids: ["docker:volume:pgdata"],
      allow_dangerous: true,
    });
  });

  // The server re-scans the selection before a job exists, which takes minutes for
  // node_modules on a large disk; nothing on the review step used to say so.
  it("stays on review, marked as starting, until the server has checked the selection", async () => {
    const reply = deferred<{ job_id: string }>();
    startResponse.mockReturnValueOnce(reply.promise);
    const { result } = renderWizard();

    let started!: Promise<void>;
    act(() => {
      started = result.current.startJob();
    });
    expect(result.current.state.step).toBe("review");
    expect(result.current.state.starting).toBe(true);

    await act(async () => {
      reply.resolve({ job_id: "job-1" });
      await started;
    });
    expect(result.current.state.starting).toBe(false);
    expect(result.current.state.step).toBe("execute");
  });

  it("sends one start however often execute is pressed while it is pending", async () => {
    const reply = deferred<{ job_id: string }>();
    startResponse.mockReturnValueOnce(reply.promise);
    const { result } = renderWizard();

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.startJob();
    });
    act(() => {
      second = result.current.startJob();
    });
    await act(async () => {
      reply.resolve({ job_id: "job-1" });
      await Promise.all([first, second]);
    });

    expect(startRequests()).toHaveLength(1);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("says why a start was refused, stays on review, and can start again", async () => {
    startResponse.mockRejectedValueOnce(
      new ApiError("job_in_progress", "a cleanup is already active", 409, null),
    );
    const { result } = renderWizard();

    await act(async () => {
      await result.current.startJob();
    });
    expect(result.current.state.step).toBe("review");
    expect(result.current.state.starting).toBe(false);
    expect(result.current.state.startError).toMatch(/running/i);

    await act(async () => {
      await result.current.startJob();
    });
    expect(startRequests()).toHaveLength(2);
    expect(result.current.state.step).toBe("execute");
    expect(result.current.state.startError).toBeNull();
  });

  it("tells the user to rescan when entries vanished since the scan", async () => {
    startResponse.mockRejectedValueOnce(
      new ApiError("unknown_entry", "Bad Request", 400, { error: { code: "unknown_entry" } }),
    );
    const { result } = renderWizard();

    await act(async () => {
      await result.current.startJob();
    });
    expect(result.current.state.startError).toMatch(/rescan/i);
  });

  // Nobody would answer the orphan's prompts, and it would hold the only job slot:
  // every later cleanup would be refused until the app restarted.
  it("cancels the job it started when the wizard closed during the check", async () => {
    const reply = deferred<{ job_id: string }>();
    startResponse.mockReturnValueOnce(reply.promise);
    const { result, unmount } = renderWizard();

    let started!: Promise<void>;
    act(() => {
      started = result.current.startJob();
    });
    unmount();
    await act(async () => {
      reply.resolve({ job_id: "job-1" });
      await started;
    });

    expect(postJson).toHaveBeenCalledWith("/clean/jobs/job-1/cancel", undefined);
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
