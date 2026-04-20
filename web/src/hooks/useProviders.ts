import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface ProviderRow {
  name: string;
  description: string;
  risk: "safe" | "reclaimable" | "dangerous";
  platforms: string[];
  available: boolean;
  required_binary: string | null;
  kind: "class" | "yaml";
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () => apiFetch<ProviderRow[]>("/providers"),
    staleTime: 60_000,
  });
}
