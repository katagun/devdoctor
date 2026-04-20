import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface DiffRow {
  provider: string;
  before_bytes: number;
  after_bytes: number;
  delta_bytes: number;
  delta_pct: number;
}

export interface DiffReport {
  before_at: string;
  after_at: string;
  rows: DiffRow[];
}

export function useDiff(from: string | null, to: string | null) {
  return useQuery({
    enabled: !!from && !!to,
    queryKey: ["diff", from, to],
    queryFn: () =>
      apiFetch<DiffReport>(`/diff?from_=${encodeURIComponent(from!)}&to_=${encodeURIComponent(to!)}`),
  });
}
