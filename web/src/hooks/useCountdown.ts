import { useEffect, useLayoutEffect, useRef, useState } from "react";

const TICK_MS = 1000;

/**
 * Milliseconds left of `totalMs`, ticking once a second while `running` is
 * true, never below zero; null when there is nothing to count down. The clock
 * starts when `running` turns on, so an estimate that arrives mid-run counts
 * from the real start; a rescan starts afresh.
 */
export function useCountdown(totalMs: number | null, running: boolean): number | null {
  // Time since this run's clock started, as of its latest tick; null before the
  // first tick, so a run shows its whole total from its first render.
  const [elapsed, setElapsed] = useState<number | null>(null);
  // Read by the tick without restarting the clock when the estimate changes.
  const totalRef = useRef(totalMs);
  useLayoutEffect(() => {
    totalRef.current = totalMs;
  }, [totalMs]);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = setInterval(() => {
      const current = Date.now() - started;
      setElapsed(current);
      // Past zero the text no longer changes; stop re-rendering the page.
      const total = totalRef.current;
      if (total !== null && current >= total) clearInterval(timer);
    }, TICK_MS);
    return () => {
      clearInterval(timer);
      // The next run counts from its own start, not from where this one stopped.
      setElapsed(null);
    };
  }, [running]);

  if (totalMs === null || !running) return null;
  return Math.max(0, totalMs - (elapsed ?? 0));
}
