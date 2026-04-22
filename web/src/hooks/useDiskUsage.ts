import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface DiskUsage {
  mount: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
}

export function useDiskUsage() {
  return useQuery({
    queryKey: ["disk-usage"],
    staleTime: 30_000,
    refetchInterval: 60_000,
    queryFn: async () => apiFetch<DiskUsage>("/disk-usage"),
  });
}
