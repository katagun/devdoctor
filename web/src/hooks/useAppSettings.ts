import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api";

export type StorageBackend = "filesystem" | "sqlite";

export interface AppSettings {
  storage_backend: StorageBackend;
  data_dir: string;
  sqlite_path: string;
  available_backends: StorageBackend[];
}

export interface AppSettingsPatch {
  storage_backend?: StorageBackend;
  data_dir?: string;
  sqlite_path?: string;
}

export function useAppSettings() {
  return useQuery({
    queryKey: ["app-settings"],
    queryFn: () => apiFetch<AppSettings>("/settings"),
    staleTime: 30_000,
  });
}

export function useUpdateAppSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: AppSettingsPatch) =>
      apiFetch<AppSettings>("/settings", {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: (settings) => {
      qc.setQueryData(["app-settings"], settings);
      qc.invalidateQueries({ queryKey: ["snapshots"] });
      qc.invalidateQueries({ queryKey: ["history"] });
      qc.invalidateQueries({ queryKey: ["disk-usage"] });
    },
  });
}
