import { useEffect, useState } from "react";

export interface SSEEvent {
  type: string;
  data: unknown;
  ts: number;
}

/**
 * Subscribe to an SSE endpoint. Listens for each of `eventNames` plus the
 * default unnamed `message`. Returns the list of events received, newest last.
 */
export function useSSE(url: string | null, eventNames: string[]) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [status, setStatus] = useState<"idle" | "open" | "closed" | "error">("idle");

  useEffect(() => {
    if (!url) {
      setStatus("idle");
      return;
    }
    const es = new EventSource(url);
    setStatus("open");

    const handlers: Array<() => void> = [];

    function register(name: string) {
      const fn = (ev: MessageEvent) => {
        let data: unknown = ev.data;
        try {
          data = JSON.parse(ev.data);
        } catch {
          /* leave raw */
        }
        setEvents((prev) => [...prev, { type: name, data, ts: Date.now() }]);
      };
      es.addEventListener(name, fn);
      handlers.push(() => es.removeEventListener(name, fn));
    }

    register("message");
    for (const n of eventNames) register(n);

    es.onerror = () => setStatus("error");

    return () => {
      for (const off of handlers) off();
      es.close();
      setStatus("closed");
    };
  }, [url, eventNames.join(",")]);

  return { events, status };
}
