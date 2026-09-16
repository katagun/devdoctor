import { useEffect, useState } from "react";
import type { ScanProgressSnapshot } from "@/lib/scanProgress";

export const SCAN_PROGRESS_URL = "/api/scan/progress";

/**
 * The running scan's latest progress snapshot while `active`, else null.
 *
 * Progress is decoration on top of the scan query: an error leaves the last
 * value in place and nothing reconnects; `idle` snapshots and any snapshot
 * from an older scan than one already shown are ignored, so a stale "done"
 * cannot flash before the new scan starts. The stream closes on `done`, on
 * `active` turning false, and on unmount.
 */
export function useScanProgress(active: boolean): ScanProgressSnapshot | null {
  const [snapshot, setSnapshot] = useState<ScanProgressSnapshot | null>(null);

  useEffect(() => {
    if (!active) {
      setSnapshot(null);
      return;
    }
    const es = new EventSource(SCAN_PROGRESS_URL);
    let highestScanId = 0;
    const onProgress = (event: MessageEvent) => {
      let next: ScanProgressSnapshot;
      try {
        next = JSON.parse(event.data) as ScanProgressSnapshot;
      } catch {
        return;
      }
      if (next.status === "idle" || next.scan_id < highestScanId) return;
      highestScanId = next.scan_id;
      setSnapshot(next);
      if (next.status === "done") es.close();
    };
    es.addEventListener("progress", onProgress);
    es.onerror = () => {
      /* keep the last snapshot; the scan query is unaffected */
    };
    return () => {
      es.removeEventListener("progress", onProgress);
      es.close();
    };
  }, [active]);

  return snapshot;
}
