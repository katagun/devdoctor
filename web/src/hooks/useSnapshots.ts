import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface ProviderTimingMeta {
  name: string;
  bytes: number;
  entries: number;
  duration_ms: number;
}

export interface SnapshotMeta {
  name: string;
  path: string;
  scanned_at: string;
  hostname: string;
  platform: string;
  note: string | null;
  total_bytes: number;
  // Telemetry — optional / nullable for v1 files.
  kind?: "auto" | "manual";
  duration_ms?: number | null;
  entry_count?: number | null;
  per_provider?: ProviderTimingMeta[] | null;
}

export function useSnapshots() {
  return useQuery({
    queryKey: ["snapshots"],
    queryFn: () => apiFetch<SnapshotMeta[]>("/snapshots"),
  });
}

interface SnapshotReportEntry {
  id: string;
  provider: string;
  label: string;
  size_bytes: number;
  risk: string;
}

export interface SnapshotReport {
  scanned_at: string;
  hostname: string;
  platform: string;
  note: string | null;
  entries: SnapshotReportEntry[];
}

export function useSnapshot(name: string | null) {
  return useQuery({
    enabled: !!name,
    queryKey: ["snapshot", name],
    queryFn: () => apiFetch<SnapshotReport>(`/snapshots/${encodeURIComponent(name!)}`),
  });
}

export function useCreateSnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { note?: string }) =>
      apiFetch<{ name: string; path: string }>("/snapshots", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["snapshots"] });
      qc.invalidateQueries({ queryKey: ["disk-usage"] });
    },
  });
}

export function useLatestAutoSnapshot() {
  return useQuery({
    queryKey: ["snapshots", "latest-auto"],
    queryFn: async () => {
      const list = await apiFetch<SnapshotMeta[]>("/snapshots?kind=auto&limit=1");
      return list[0] ?? null;
    },
    staleTime: 30_000,
  });
}
