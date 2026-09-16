import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";
import type { CacheTableRow } from "@/components/CacheTable";

interface ScanResponseEntry {
  id: string;
  provider: string;
  label: string;
  path: string | null;
  size_bytes: number;
  footprint_bytes?: number | null;
  reclaimable_bytes?: number | null;
  shared_bytes?: number;
  mtime: number | null;
  risk: "safe" | "reclaimable" | "dangerous";
  recipe: string[];
  owner?: string | null;
  group?: string | null;
  perms?: string | null;
}

interface ScanResponse {
  entries: ScanResponseEntry[];
  scanned_at: string;
  hostname: string;
  platform: string;
  skipped_paths: string[];
  total_reclaimable_bytes?: number;
}

export interface UseScanOptions {
  minSize?: string;
  provider?: string;
  // Cadence control — maps to React Query's staleTime. `Infinity` + refetchOnMount=false == manual only.
  staleTime?: number;
  refetchOnMount?: boolean;
  /** Minimum interval (ms) between auto-snapshot writes on the server. Every
   * scan asks for an auto-snapshot; the server checks the most recent one's
   * mtime and skips writes inside this window, so the user's cadence holds
   * however many pages or refetches ask. Never below AUTO_SNAPSHOT_FLOOR_MS. */
  snapshotMinIntervalMs?: number;
}

// The "live" cadence has a zero staleTime; without a floor every page mount and
// refresh would write a snapshot and the history would hold minutes, not days.
export const AUTO_SNAPSHOT_FLOOR_MS = 5 * 60_000;

/**
 * The scan query. Its key is the server-side filters alone, so every page
 * asking for the same filters shares one request and one cached result — the
 * Dashboard and the Disk page no longer run a scan each (#104).
 */
export function useScan(params: UseScanOptions = {}) {
  const { staleTime, refetchOnMount, snapshotMinIntervalMs, ...filters } = params;
  return useQuery({
    queryKey: ["scan", filters],
    staleTime,
    refetchOnMount,
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (filters.minSize) qs.set("min_size", filters.minSize);
      if (filters.provider) qs.set("provider", filters.provider);
      qs.set("snapshot", "true");
      if (snapshotMinIntervalMs === Number.POSITIVE_INFINITY) {
        // Manual cadence: signal "never auto-snapshot again if any exist".
        qs.set("snapshot_min_interval_ms", String(Number.MAX_SAFE_INTEGER));
      } else {
        const interval = Math.max(snapshotMinIntervalMs ?? 0, AUTO_SNAPSHOT_FLOOR_MS);
        qs.set("snapshot_min_interval_ms", String(Math.floor(interval)));
      }
      const query = `?${qs}`;
      const raw = await apiFetch<ScanResponse>(`/scan${query}`);
      const rows: CacheTableRow[] = raw.entries.map((e) => {
        // null means the provider deliberately left the entry unmeasured (for
        // example an advice-only git worktree); only a missing field falls back
        // to size_bytes, for providers that predate explicit usage.
        const footprint =
          e.footprint_bytes === undefined ? e.size_bytes : e.footprint_bytes;
        const reclaimable =
          e.reclaimable_bytes !== undefined
            ? e.reclaimable_bytes
            : e.risk === "dangerous"
              ? null
              : e.size_bytes;
        return {
          id: e.id,
          provider: e.provider,
          label: e.label,
          path: e.path ?? "—",
          size_bytes: footprint ?? 0,
          footprint_bytes: footprint,
          reclaimable_bytes: reclaimable,
          shared_bytes: e.shared_bytes ?? 0,
          risk: e.risk,
          mtime: e.mtime,
          recipeHint: e.recipe[0] ?? "",
          owner: e.owner ?? null,
          group: e.group ?? null,
          perms: e.perms ?? null,
        };
      });
      return {
        rows,
        totalBytes:
          raw.total_reclaimable_bytes ??
          rows
            .filter((entry) => entry.risk !== "dangerous")
            .reduce((sum, entry) => sum + (entry.reclaimable_bytes ?? 0), 0),
        scannedAt: raw.scanned_at,
      };
    },
  });
}
