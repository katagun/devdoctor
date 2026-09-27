import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { useSSE } from "@/hooks/useSSE";

// Minimal fake EventSource.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: ((e: Event) => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  removeEventListener() {}
  close() {}
  emit(type: string, data: string) {
    for (const fn of this.listeners[type] ?? []) {
      fn(new MessageEvent(type, { data }));
    }
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof FakeEventSource }).EventSource =
    FakeEventSource;
});

describe("useSSE", () => {
  it("collects incoming events by type", async () => {
    const { result } = renderHook(() =>
      useSSE("/api/clean/jobs/abc/events", ["prompt", "done"]),
    );

    const es = FakeEventSource.instances[0];
    act(() => es.emit("prompt", JSON.stringify({ entry_id: "1" })));
    act(() => es.emit("done", JSON.stringify({ results: [] })));

    await waitFor(() => {
      expect(result.current.events).toHaveLength(2);
      expect(result.current.events[0].type).toBe("prompt");
    });
  });

  it("is idle without a url, open while subscribed, and error once the stream fails", () => {
    const { result, rerender } = renderHook(({ url }) => useSSE(url, ["done"]), {
      initialProps: { url: null as string | null },
    });
    expect(result.current.status).toBe("idle");
    expect(FakeEventSource.instances).toHaveLength(0);

    rerender({ url: "/api/a" });
    expect(result.current.status).toBe("open");

    act(() => FakeEventSource.instances[0].onerror?.(new Event("error")));
    expect(result.current.status).toBe("error");

    // A new stream starts out open; dropping the url goes back to idle.
    rerender({ url: "/api/b" });
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(result.current.status).toBe("open");
    rerender({ url: null });
    expect(result.current.status).toBe("idle");
  });
});
