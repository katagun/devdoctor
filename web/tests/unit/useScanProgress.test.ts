import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useScanProgress } from "@/hooks/useScanProgress";
import type { ScanProgressSnapshot } from "@/lib/scanProgress";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: ((e: Event) => void) | null = null;
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
    this.emitRaw(type, JSON.stringify(data));
  }
  emitRaw(type: string, rawData: string) {
    for (const fn of this.listeners[type] ?? []) {
      fn(new MessageEvent(type, { data: rawData }));
    }
  }
}

function snap(over: Partial<ScanProgressSnapshot>): ScanProgressSnapshot {
  return {
    scan_id: 1,
    status: "running",
    started_at: null,
    total: 3,
    done: 1,
    running: ["b"],
    entries: 1,
    bytes: 10,
    providers: [],
    ...over,
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof FakeEventSource }).EventSource =
    FakeEventSource;
});

describe("useScanProgress", () => {
  it("opens the stream only while active and closes it when inactive", () => {
    const { result, rerender } = renderHook(({ active }) => useScanProgress(active), {
      initialProps: { active: false },
    });
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current).toBeNull();

    rerender({ active: true });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/scan/progress");

    rerender({ active: false });
    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(result.current).toBeNull();
  });

  it("keeps the latest snapshot and ignores idle ones", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ status: "idle", scan_id: 0, total: 0, done: 0})));
    expect(result.current).toBeNull();
    act(() => es.emit("progress", snap({ done: 1 })));
    act(() => es.emit("progress", snap({ done: 2 })));
    expect(result.current?.done).toBe(2);
  });

  it("ignores a snapshot from an older scan than one already shown", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ scan_id: 5, done: 1 })));
    act(() => es.emit("progress", snap({ scan_id: 4, status: "done", done: 3 })));
    expect(result.current?.scan_id).toBe(5);
    expect(result.current?.done).toBe(1);
  });

  it("closes on a done snapshot and keeps it until inactive", () => {
    const { result, rerender } = renderHook(({ active }) => useScanProgress(active), {
      initialProps: { active: true },
    });
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ status: "running", done: 1, running: ["b"] })));
    act(() => es.emit("progress", snap({ status: "done", done: 3, running: [] })));
    expect(es.closed).toBe(true);
    expect(result.current?.status).toBe("done");
    rerender({ active: false });
    expect(result.current).toBeNull();
  });

  it("ignores a stale done before any running snapshot", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ status: "done", done: 3, running: [], scan_id: 1 })));
    expect(result.current).toBeNull();
    expect(es.closed).toBe(false);
    act(() => es.emit("progress", snap({ scan_id: 2, done: 1 })));
    expect(result.current?.scan_id).toBe(2);
  });

  it("ignores a malformed payload", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    expect(() => act(() => es.emitRaw("progress", "not json"))).not.toThrow();
    expect(result.current).toBeNull();
  });

  it("keeps the last value on a stream error", () => {
    const { result } = renderHook(() => useScanProgress(true));
    const es = FakeEventSource.instances[0];
    act(() => es.emit("progress", snap({ done: 2 })));
    act(() => es.onerror?.(new Event("error")));
    expect(result.current?.done).toBe(2);
    expect(es.closed).toBe(true);
  });

  it("closes the stream on unmount", () => {
    const { unmount } = renderHook(() => useScanProgress(true));
    unmount();
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });
});
