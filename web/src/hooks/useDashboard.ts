import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";
import type { DiskMosaicInput } from "@/lib/dashboard";

export interface DiskDashboardProviderTotal {
  provider: string;
  bytes: number;
  count: number;
  footprint_bytes: number | null;
  reclaimable_bytes: number | null;
  shared_bytes: number;
}

export interface DiskDashboardSummary {
  scanned_at: string;
  hostname: string;
  platform: string;
  total_bytes: number;
  entry_count: number;
  entries: DiskMosaicInput[];
  provider_totals: DiskDashboardProviderTotal[];
  total_footprint_bytes: number | null;
  total_reclaimable_bytes: number | null;
  total_shared_bytes: number;
  unknown_reclaimable_entries: number;
}

export function useDiskDashboardSummary(providerParam?: string) {
  return useQuery({
    queryKey: ["dashboard", "disk-summary", providerParam ?? "all"],
    queryFn: () =>
      apiFetch<DiskDashboardSummary | null>(
        `/dashboard/disk-summary${providerQuery(providerParam)}`,
      ),
    staleTime: 30_000,
  });
}

function providerQuery(providerParam: string | undefined): string {
  if (!providerParam) return "";
  const qs = new URLSearchParams();
  qs.set("provider", providerParam);
  return `?${qs}`;
}
