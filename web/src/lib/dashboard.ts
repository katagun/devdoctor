import type { MemoryConsumerKind } from "@/hooks/useMemory";

export type MosaicTone =
  | "safe"
  | "reclaimable"
  | "dangerous"
  | "browser"
  | "electron"
  | "docker"
  | "llm"
  | "app"
  | "process"
  | "other";

export interface MosaicDatum {
  id: string;
  label: string;
  value: number;
  tone: MosaicTone;
  detail?: string;
}

interface WeightedInput {
  id: string;
  label: string;
  value: number;
  tone: MosaicTone;
  detail?: string;
}

export interface DiskMosaicInput {
  id: string;
  provider: string;
  label: string;
  size_bytes: number;
  risk: "safe" | "reclaimable" | "dangerous";
}

export interface MemoryMosaicInput {
  id: string;
  name: string;
  kind: "browser" | "electron" | "docker" | "llm" | "app" | "process";
  selected: boolean;
  rss_bytes: number;
  consumer_count: number;
}

export interface MemoryConsumerInput {
  id: string;
  name: string;
  kind: MemoryConsumerKind;
  rss_bytes: number;
}

export interface DiskProviderTotal {
  provider: string;
  bytes: number;
  count: number;
}

export function buildDiskMosaicItems(
  rows: DiskMosaicInput[],
  maxItems = 12,
): MosaicDatum[] {
  return topWeightedItems(
    rows
      .filter((row) => row.risk !== "dangerous")
      .map((row) => ({
        id: row.id,
        label: row.label,
        value: row.size_bytes,
        tone: row.risk,
        detail: row.provider,
      })),
    maxItems,
    {
      id: "disk-other",
      label: "other disk entries",
      tone: "other",
    },
  );
}

export function buildMemoryMosaicItems(
  rows: MemoryMosaicInput[],
  maxItems = 10,
): MosaicDatum[] {
  return topWeightedItems(
    rows
      .filter((row) => row.selected)
      .map((row) => ({
        id: row.id,
        label: row.name,
        value: row.rss_bytes,
        tone: row.kind,
        detail: `${row.consumer_count} process${row.consumer_count === 1 ? "" : "es"}`,
      })),
    maxItems,
    {
      id: "memory-other",
      label: "other memory providers",
      tone: "other",
    },
  );
}

export function diskProviderTotals(rows: DiskMosaicInput[]): DiskProviderTotal[] {
  const totals = new Map<string, DiskProviderTotal>();
  for (const row of rows) {
    if (row.size_bytes <= 0) continue;
    const existing = totals.get(row.provider);
    if (existing) {
      existing.bytes += row.size_bytes;
      existing.count += 1;
    } else {
      totals.set(row.provider, {
        provider: row.provider,
        bytes: row.size_bytes,
        count: 1,
      });
    }
  }
  return [...totals.values()].sort((a, b) => b.bytes - a.bytes);
}

export function topMemoryConsumers<T extends MemoryConsumerInput>(
  rows: T[],
  limit = 5,
): T[] {
  return [...rows]
    .filter((row) => row.rss_bytes > 0)
    .sort((a, b) => b.rss_bytes - a.rss_bytes)
    .slice(0, limit);
}

function topWeightedItems(
  rows: WeightedInput[],
  maxItems: number,
  aggregate: Pick<MosaicDatum, "id" | "label" | "tone">,
): MosaicDatum[] {
  const sorted = rows
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value);
  if (sorted.length <= maxItems) return sorted;

  const visibleCount = Math.max(1, maxItems - 1);
  const visible = sorted.slice(0, visibleCount);
  const hidden = sorted.slice(visibleCount);
  const hiddenValue = hidden.reduce((sum, row) => sum + row.value, 0);
  return [
    ...visible,
    {
      ...aggregate,
      value: hiddenValue,
      detail: `${hidden.length} item${hidden.length === 1 ? "" : "s"}`,
    },
  ];
}
