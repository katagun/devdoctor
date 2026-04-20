import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface SnapshotMeta {
  name: string;
  path: string;
  scanned_at: string;
  hostname: string;
  platform: string;
  note: string | null;
  total_bytes: number;
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["snapshots"] }),
  });
}
