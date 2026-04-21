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
}

export function useScan(params: UseScanOptions = {}) {
  const { staleTime, refetchOnMount, ...filters } = params;
  return useQuery({
    queryKey: ["scan", filters],
    staleTime,
    refetchOnMount,
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (filters.risk) qs.set("risk", filters.risk);
      if (filters.minSize) qs.set("min_size", filters.minSize);
      if (filters.provider) qs.set("provider", filters.provider);
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
      }));
      return {
        rows,
        totalBytes: raw.entries.reduce((a, b) => a + b.size_bytes, 0),
        scannedAt: raw.scanned_at,
      };
    },
  });
}
