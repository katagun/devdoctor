import { useEffect, useState } from "react";

const TICK_MS = 1000;

/**
 * Milliseconds left of `totalMs`, ticking once a second while `running` is
 * true, never below zero; null when there is nothing to count down. Restarts
 * from the total each time `running` turns on, so a rescan starts afresh.
 */
export function useCountdown(totalMs: number | null, running: boolean): number | null {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running || totalMs === null) {
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
      if (current - started >= totalMs) clearInterval(timer);
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [running, totalMs]);

  if (totalMs === null || !running || startedAt === null) return null;
  return Math.max(0, totalMs - (now - startedAt));
}
