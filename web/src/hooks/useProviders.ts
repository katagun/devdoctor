import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export interface ProviderRow {
  id: string;
  name: string;
  family: string;
  description: string;
  risk: "safe" | "reclaimable" | "dangerous";
  platforms: string[];
  available: boolean;
  required_binary: string | null;
  kind: "class" | "yaml";
  origin: "builtin" | "manifest";
  // New: details panel data. All optional — populated based on `kind`.
  details: string | null;
  raw_paths: string[] | null;
  resolved_paths: string[] | null;
  recipe_template: string[] | null;
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: async () => {
      const rows = await apiFetch<ProviderRow[]>("/providers");
      return rows.map((row) => ({
        ...row,
        id: row.id ?? row.name,
        family: row.family ?? "other",
        origin: row.origin ?? (row.kind === "yaml" ? "manifest" : "builtin"),
      }));
    },
    staleTime: 60_000,
  });
}
