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

export function useScan(params: { risk?: string; minSize?: string; provider?: string } = {}) {
  return useQuery({
    queryKey: ["scan", params],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (params.risk) qs.set("risk", params.risk);
      if (params.minSize) qs.set("min_size", params.minSize);
      if (params.provider) qs.set("provider", params.provider);
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
      return { rows, totalBytes: raw.entries.reduce((a, b) => a + b.size_bytes, 0) };
    },
  });
}
