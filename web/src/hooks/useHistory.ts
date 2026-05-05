import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface CleanupResultEntry {
  entry_id: string;
  status: string;
  freed_bytes: number;
  message?: string | null;
}

export interface CleanupEvent {
  type: "cleanup";
  at: string;
  job_id: string;
  outcome: "ok" | "cancelled" | "error" | string;
  total_freed_bytes: number;
  results: CleanupResultEntry[];
  error?: string;
}

export interface SnapshotEvent {
  type: "snapshot";
  at: string;
  name: string;
  total_bytes: number;
  entry_count: number;
  note: string | null;
}

export interface MemoryActionEvent {
  type: "memory_action";
  at: string;
  action_id: string;
  action_kind: string;
  target_id: string;
  label: string;
  estimated_bytes: number | null;
  risk: "safe" | "reclaimable" | "dangerous" | string | null;
  status: "ok" | "error" | "unsupported" | string;
  message: string;
}

export type HistoryEvent = CleanupEvent | SnapshotEvent | MemoryActionEvent;

export function useHistory() {
  return useQuery({
    queryKey: ["history"],
    queryFn: () => apiFetch<{ events: HistoryEvent[] }>("/history"),
    refetchOnMount: true,
  });
}
