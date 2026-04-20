import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { useSSE } from "@/hooks/useSSE";

// Minimal fake EventSource.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
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
});
