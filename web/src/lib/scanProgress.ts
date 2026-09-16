import { humanBytes } from "@/lib/format";

/** Mirror of ScanProgressSnapshot.to_json() in src/devdoctor/web/scan_progress.py. */
export interface ProviderProgress {
  name: string;
  status: "pending" | "running" | "done";
  duration_ms: number | null;
  entries: number;
  bytes: number;
}

export interface ScanProgressSnapshot {
  scan_id: number;
  status: "idle" | "running" | "done";
  started_at: string | null;
  total: number;
  done: number;
  running: string[];
  entries: number;
  bytes: number;
  providers: ProviderProgress[];
}

export interface ScanProgressParts {
  providers: string;
  /** null until a provider has finished, so a first provider that found nothing reads "0B found". */
  found: string | null;
  /** null when nothing is running; at most MAX_RUNNING_NAMES names, then " +N". */
  running: string | null;
  /** Every provider is done; the scan is reconciling, sorting and writing. */
  finishing: boolean;
}

export const MAX_RUNNING_NAMES = 3;

export function formatScanProgress(snapshot: ScanProgressSnapshot): ScanProgressParts {
  const shown = snapshot.running.slice(0, MAX_RUNNING_NAMES);
  const more = snapshot.running.length - shown.length;
  return {
    providers: `${snapshot.done}/${snapshot.total} providers`,
    found: snapshot.done > 0 ? `${humanBytes(snapshot.bytes)} found` : null,
    running:
      shown.length > 0 ? `running: ${shown.join(", ")}${more > 0 ? ` +${more}` : ""}` : null,
    finishing: snapshot.status === "done",
  };
}
