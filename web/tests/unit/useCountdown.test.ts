import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCountdown } from "@/hooks/useCountdown";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useCountdown", () => {
  it("is null until there is a total and the countdown is running", () => {
    const { result, rerender } = renderHook(
      ({ total, running }) => useCountdown(total, running),
      { initialProps: { total: null as number | null, running: true } },
    );
    expect(result.current).toBeNull();
    rerender({ total: 5000, running: false });
    expect(result.current).toBeNull();
  });

  it("counts down once a second from the total and stops at zero", () => {
    const { result } = renderHook(() => useCountdown(2500, true));
    expect(result.current).toBe(2500);
    act(() => void vi.advanceTimersByTime(1000));
    expect(result.current).toBe(1500);
    act(() => void vi.advanceTimersByTime(1000));
    expect(result.current).toBe(500);
    act(() => void vi.advanceTimersByTime(3000));
    expect(result.current).toBe(0);
  });

  it("restarts from the total each time running turns on", () => {
    const { result, rerender } = renderHook(
      ({ running }) => useCountdown(3000, running),
      { initialProps: { running: true } },
    );
    act(() => void vi.advanceTimersByTime(2000));
    expect(result.current).toBe(1000);
    rerender({ running: false });
    expect(result.current).toBeNull();
    rerender({ running: true });
    expect(result.current).toBe(3000);
  });

  it("shows the whole total from the first render of a run, with no blank render first", () => {
    const rendered: Array<number | null> = [];
    const { rerender } = renderHook(
      ({ running }) => {
        const remaining = useCountdown(4000, running);
        rendered.push(remaining);
        return remaining;
      },
      { initialProps: { running: false } },
    );
    rendered.length = 0;
    rerender({ running: true });
    expect(rendered).toEqual([4000]);
  });

  it("keeps the start anchored when the total arrives mid-run", () => {
    // On a cold load the scan starts before the estimate query resolves.
    const { result, rerender } = renderHook(
      ({ total }) => useCountdown(total, true),
      { initialProps: { total: null as number | null } },
    );
    expect(result.current).toBeNull();
    act(() => void vi.advanceTimersByTime(2000));
    rerender({ total: 5000 });
    expect(result.current).toBe(3000);
  });

  it("stops ticking once past zero when the total arrives mid-run", () => {
    const { result, rerender } = renderHook(
      ({ total }) => useCountdown(total, true),
      { initialProps: { total: null as number | null } },
    );
    act(() => void vi.advanceTimersByTime(1000));
    rerender({ total: 2000 });
    act(() => void vi.advanceTimersByTime(1000));
    expect(result.current).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });
});
