import type { DiskMosaicInput } from "@/lib/dashboard";

const KEY = "devdoctor.dashboard.disk.v1";

export interface DashboardDiskCache {
  scannedAt: string;
  totalBytes: number;
  providerParam: string | null;
  rows: DiskMosaicInput[];
}

export function readDashboardDiskCache(
  providerParam: string | undefined,
): DashboardDiskCache | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = parseDashboardDiskCache(JSON.parse(raw));
    if (!parsed) return null;
    if (parsed.providerParam !== (providerParam ?? null)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeDashboardDiskCache(cache: DashboardDiskCache): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(cache));
  } catch {
    /* ignore private-mode/quota errors */
  }
}

function parseDashboardDiskCache(value: unknown): DashboardDiskCache | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Partial<DashboardDiskCache>;
  if (typeof row.scannedAt !== "string") return null;
  if (typeof row.totalBytes !== "number" || row.totalBytes < 0) return null;
  if (row.providerParam !== null && typeof row.providerParam !== "string") return null;
  if (!Array.isArray(row.rows)) return null;
  const rows = row.rows.filter(isDiskRow);
  return {
    scannedAt: row.scannedAt,
    totalBytes: row.totalBytes,
    providerParam: row.providerParam ?? null,
    rows,
  };
}

function isDiskRow(value: unknown): value is DiskMosaicInput {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<DiskMosaicInput>;
  return (
    typeof row.id === "string" &&
    typeof row.provider === "string" &&
    typeof row.label === "string" &&
    typeof row.size_bytes === "number" &&
    row.size_bytes >= 0 &&
    (row.risk === "safe" || row.risk === "reclaimable" || row.risk === "dangerous")
  );
}
