import { useEffect, useRef, useState } from "react";

const TICK_MS = 1000;

/**
 * Milliseconds left of `totalMs`, ticking once a second while `running` is
 * true, never below zero; null when there is nothing to count down. The clock
 * starts when `running` turns on, so an estimate that arrives mid-run counts
 * from the real start; a rescan starts afresh.
 */
export function useCountdown(totalMs: number | null, running: boolean): number | null {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  // Read by the tick without restarting the clock when the estimate changes.
  const totalRef = useRef(totalMs);
  totalRef.current = totalMs;

  useEffect(() => {
    if (!running) {
      setStartedAt(null);
      return;
    }
    const started = Date.now();
    setStartedAt(started);
    setNow(started);
    const timer = setInterval(() => {
      const current = Date.now();
      setNow(current);
      // Past zero the text no longer changes; stop re-rendering the page.
      const total = totalRef.current;
      if (total !== null && current - started >= total) clearInterval(timer);
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [running]);

  if (totalMs === null || !running || startedAt === null) return null;
  return Math.max(0, totalMs - (now - startedAt));
}
