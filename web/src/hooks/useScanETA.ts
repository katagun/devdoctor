import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import type { SnapshotMeta } from "@/hooks/useSnapshots";

const MIN_SAMPLES = 3;
const LIMIT = 20;

export interface UseScanETAResult {
  etaMs: number | null;
  providerCount: number;
  sampleSize: number;
}

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const sorted = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function useScanETA(): UseScanETAResult | null {
  const { isEnabled } = useSelectedProviders();
  const { data } = useQuery({
    queryKey: ["scan-eta", "auto", LIMIT],
    queryFn: () => apiFetch<SnapshotMeta[]>(`/snapshots?kind=auto&limit=${LIMIT}`),
    staleTime: 30_000,
  });

  if (!data) return null;

  const usable = data.filter(
    (s) => typeof s.duration_ms === "number" && Array.isArray(s.per_provider),
  );
  if (usable.length < MIN_SAMPLES) {
    return { etaMs: null, providerCount: 0, sampleSize: usable.length };
  }

  const perProvider = new Map<string, number[]>();
  for (const snap of usable) {
    for (const pt of snap.per_provider ?? []) {
      if (!isEnabled(pt.name)) continue;
      const arr = perProvider.get(pt.name) ?? [];
      arr.push(pt.duration_ms);
      perProvider.set(pt.name, arr);
    }
  }

  let etaMs = 0;
  for (const durations of perProvider.values()) {
    etaMs += median(durations);
  }

  return {
    etaMs: Math.round(etaMs),
    providerCount: perProvider.size,
    sampleSize: usable.length,
  };
}
