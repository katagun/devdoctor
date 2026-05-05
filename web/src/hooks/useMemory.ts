import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export type MemoryPressure = "ok" | "warn" | "critical" | "unknown";
export type MemoryConsumerKind =
  | "app"
  | "process"
  | "browser"
  | "electron"
  | "docker"
  | "llm"
  | "other";
export type MemoryActionKind =
  | "inspect_browser"
  | "discard_tabs"
  | "stop_container"
  | "stop_service"
  | "quit_app"
  | "terminate_process";
export type MemoryActionRisk = "safe" | "reclaimable" | "dangerous";
export type MemorySuggestionConfidence = "low" | "medium" | "high";

export interface SystemMemory {
  total_bytes: number;
  available_bytes: number;
  used_bytes: number;
  swap_used_bytes: number | null;
  compressed_bytes: number | null;
  pressure: MemoryPressure;
}

export interface MemoryConsumer {
  id: string;
  pid: number | null;
  parent_pid: number | null;
  name: string;
  kind: MemoryConsumerKind;
  rss_bytes: number;
  private_bytes: number | null;
  command: string | null;
  children: MemoryConsumer[];
}

export interface MemoryAction {
  id: string;
  kind: MemoryActionKind;
  label: string;
  target_id: string;
  estimated_bytes: number | null;
  risk: MemoryActionRisk;
}

export interface MemoryActionExecuteRequest {
  id: string;
  kind: MemoryActionKind;
  target_id: string;
  label?: string | null;
  estimated_bytes?: number | null;
  risk?: MemoryActionRisk | null;
  confirmed: boolean;
}

export interface MemoryActionExecuteResult {
  action_id: string;
  status: "ok" | "error" | "unsupported";
  message: string;
}

export interface MemorySuggestion {
  id: string;
  title: string;
  reason: string;
  estimated_bytes: number | null;
  confidence: MemorySuggestionConfidence;
  actions: MemoryAction[];
}

export interface MemoryProviderTotal {
  id: string;
  name: string;
  kind: "browser" | "electron" | "docker" | "llm" | "app" | "process";
  selected: boolean;
  rss_bytes: number;
  consumer_count: number;
}

export interface MemoryReport {
  scanned_at: string;
  hostname: string;
  platform: string;
  system: SystemMemory;
  consumers: MemoryConsumer[];
  provider_totals: MemoryProviderTotal[];
  suggestions: MemorySuggestion[];
}

export interface MemoryObservationMeta {
  id: string;
  scanned_at: string;
  pressure: MemoryPressure;
  total_bytes: number;
  available_bytes: number;
  used_bytes: number;
  swap_used_bytes: number | null;
  compressed_bytes: number | null;
  top_consumer_name: string | null;
  top_consumer_kind: MemoryConsumerKind | null;
  top_consumer_rss_bytes: number | null;
  suggestion_count: number;
}

export interface MemoryHistory {
  observations: MemoryObservationMeta[];
}

export interface MemorySnapshotMeta {
  name: string;
  created_at: string;
  scanned_at: string;
  note: string | null;
  pressure: MemoryPressure;
  total_bytes: number;
  available_bytes: number;
  used_bytes: number;
  top_consumer_name: string | null;
  top_consumer_kind: MemoryConsumerKind | null;
  top_consumer_rss_bytes: number | null;
}

export interface MemorySnapshotDiff {
  before: MemorySnapshotMeta;
  after: MemorySnapshotMeta;
  available_delta_bytes: number;
  used_delta_bytes: number;
  swap_delta_bytes: number | null;
  compressed_delta_bytes: number | null;
  top_consumer_deltas: Array<{
    id: string;
    name: string;
    kind: MemoryConsumerKind;
    before_rss_bytes: number;
    after_rss_bytes: number;
    delta_rss_bytes: number;
  }>;
  added_suggestion_ids: string[];
  removed_suggestion_ids: string[];
}

export interface MemorySource {
  id: string;
  name: string;
  kind: "system" | "process" | "docker" | "llm" | "browser";
  status: "available" | "unavailable" | "planned";
  description: string;
  detail: string | null;
}

export interface MemoryProvider {
  id: string;
  name: string;
  kind: "browser" | "electron" | "docker" | "llm" | "app" | "process";
  status: "available" | "unavailable" | "planned";
  description: string;
  detail: string | null;
  consumer_kinds: MemoryConsumerKind[];
}

export interface MemoryWorkload {
  id: string;
  label: string;
  kind: "llm" | "docker" | "browser" | "developer" | "custom";
  required_bytes: number;
  description: string;
}

export interface MemoryPlanAction {
  suggestion_id: string;
  action_id: string;
  label: string;
  estimated_bytes: number | null;
  risk: MemoryActionRisk;
  confidence: MemorySuggestionConfidence;
}

export interface MemoryPlan {
  workload: MemoryWorkload;
  fits_now: boolean;
  required_bytes: number;
  available_bytes: number;
  os_reserve_bytes: number;
  safety_margin_bytes: number;
  usable_bytes: number;
  deficit_bytes: number;
  planned_reclaim_bytes: number;
  remaining_deficit_bytes: number;
  actions: MemoryPlanAction[];
}

export interface MemoryPlanRequest {
  workload_id?: string | null;
  custom_label?: string | null;
  custom_required_bytes?: number | null;
  safety_margin_bytes?: number | null;
  providers?: string[] | null;
}

function providerQuery(providerIds: string[] | undefined): string {
  if (providerIds === undefined) return "";
  const qs = new URLSearchParams();
  qs.set("provider", providerIds.join(","));
  return `?${qs}`;
}

export function useMemory(providerIds?: string[]) {
  return useQuery({
    queryKey: ["memory", providerIds === undefined ? "all" : providerIds.join(",")],
    staleTime: 5_000,
    refetchInterval: 10_000,
    queryFn: () => apiFetch<MemoryReport>(`/memory${providerQuery(providerIds)}`),
  });
}

export function useMemoryWorkloads(enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["memory-workloads"],
    queryFn: () => apiFetch<MemoryWorkload[]>("/memory/workloads"),
    staleTime: 60_000,
  });
}

export function useMemoryPlan() {
  return useMutation({
    mutationFn: (request: MemoryPlanRequest) =>
      apiFetch<MemoryPlan>("/memory/plan", {
        method: "POST",
        body: JSON.stringify(request),
      }),
  });
}

export function useExecuteMemoryAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (request: MemoryActionExecuteRequest) =>
      apiFetch<MemoryActionExecuteResult>("/memory/actions", {
        method: "POST",
        body: JSON.stringify(request),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory"] });
      qc.invalidateQueries({ queryKey: ["memory-history"] });
    },
  });
}

export function useMemoryHistory(enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["memory-history"],
    queryFn: () => apiFetch<MemoryHistory>("/memory/history?limit=200"),
    staleTime: 10_000,
  });
}

export function useMemorySnapshots(enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["memory-snapshots"],
    queryFn: () => apiFetch<MemorySnapshotMeta[]>("/memory/snapshots"),
    staleTime: 10_000,
  });
}

export function useCreateMemorySnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      note,
      providerIds,
    }: {
      note: string | null;
      providerIds?: string[];
    }) =>
      apiFetch<MemorySnapshotMeta>(`/memory/snapshots${providerQuery(providerIds)}`, {
        method: "POST",
        body: JSON.stringify({ note }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory-snapshots"] });
      qc.invalidateQueries({ queryKey: ["memory-history"] });
    },
  });
}

export function useMemorySnapshotDiff(
  from: string | null,
  to: string | null,
  enabled = true,
) {
  return useQuery({
    enabled: enabled && !!from && !!to,
    queryKey: ["memory-snapshot-diff", from, to],
    queryFn: () =>
      apiFetch<MemorySnapshotDiff>(
        `/memory/snapshots/diff?from_=${encodeURIComponent(from!)}&to_=${encodeURIComponent(to!)}`,
      ),
    staleTime: 10_000,
  });
}

export function useMemorySources(enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["memory-sources"],
    queryFn: () => apiFetch<MemorySource[]>("/memory/sources"),
    staleTime: 60_000,
  });
}

export function useMemoryProviders(enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["memory-providers"],
    queryFn: () => apiFetch<MemoryProvider[]>("/memory/providers"),
    staleTime: 60_000,
  });
}
