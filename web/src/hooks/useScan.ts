import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";
import type { CacheTableRow } from "@/components/CacheTable";

interface ScanResponseEntry {
  id: string;
  provider: string;
  label: string;
  path: string | null;
  size_bytes: number;
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
}

export interface UseScanOptions {
  risk?: string;
  minSize?: string;
  provider?: string;
  // Cadence control — maps to React Query's staleTime. `Infinity` + refetchOnMount=false == manual only.
  staleTime?: number;
  refetchOnMount?: boolean;
  /** When true, this scan writes an auto-snapshot. Set for the cold page
   * load and explicit "Rescan now"; leave false/undefined for the pending
   * re-fetches TanStack Query performs on its own. */
  explicit?: boolean;
  /** Minimum interval (ms) between auto-snapshot writes on the server.
   * Filter-chip changes create new query keys and trigger fresh fetches —
   * without this, every chip click would write another auto-snapshot
   * regardless of the user's cadence preference. The server checks the
   * most recent auto-snapshot's mtime and skips writes inside this window. */
  snapshotMinIntervalMs?: number;
}

export function useScan(params: UseScanOptions = {}) {
  const {
    staleTime,
    refetchOnMount,
    explicit,
    snapshotMinIntervalMs,
    ...filters
  } = params;
  return useQuery({
    queryKey: ["scan", filters, explicit ? "explicit" : "implicit"],
    staleTime,
    refetchOnMount,
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (filters.risk) qs.set("risk", filters.risk);
      if (filters.minSize) qs.set("min_size", filters.minSize);
      if (filters.provider) qs.set("provider", filters.provider);
      if (explicit) {
        qs.set("snapshot", "true");
        if (
          snapshotMinIntervalMs !== undefined &&
          Number.isFinite(snapshotMinIntervalMs) &&
          snapshotMinIntervalMs > 0
        ) {
          qs.set("snapshot_min_interval_ms", String(Math.floor(snapshotMinIntervalMs)));
        } else if (snapshotMinIntervalMs === Number.POSITIVE_INFINITY) {
          // Manual cadence: signal "never auto-snapshot again if any exist".
          qs.set("snapshot_min_interval_ms", String(Number.MAX_SAFE_INTEGER));
        }
      }
      const query = qs.toString() ? `?${qs}` : "";
      const raw = await apiFetch<ScanResponse>(`/scan${query}`);
      const rows: CacheTableRow[] = raw.entries.map((e) => ({
        id: e.id,
        provider: e.provider,
        label: e.label,
        path: e.path ?? "—",
        size_bytes: e.size_bytes,
        risk: e.risk,
        mtime: e.mtime,
        recipeHint: e.recipe[0] ?? "",
        owner: e.owner ?? null,
        group: e.group ?? null,
        perms: e.perms ?? null,
      }));
      return {
        rows,
        totalBytes: raw.entries
          .filter((e) => e.risk !== "dangerous")
          .reduce((a, b) => a + b.size_bytes, 0),
        scannedAt: raw.scanned_at,
      };
    },
  });
}
