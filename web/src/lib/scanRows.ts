import type { CacheTableRow } from "@/components/CacheTable";

export interface MinSizePartition {
  visibleRows: CacheTableRow[];
  hiddenRows: CacheTableRow[];
  visibleBytes: number;
  hiddenBytes: number;
}

/**
 * Split scan rows at the minimum-size setting. Unmeasured rows (footprint null)
 * are never hidden as "small": their size is unknown, not below the threshold.
 */
export function partitionByMinSize(
  rows: CacheTableRow[],
  threshold: number,
): MinSizePartition {
  const isHidden = (row: CacheTableRow) =>
    threshold > 0 && row.footprint_bytes !== null && row.size_bytes < threshold;
  const visibleRows = rows.filter((row) => !isHidden(row));
  const hiddenRows = rows.filter(isHidden);
  const sum = (list: CacheTableRow[]) => list.reduce((total, row) => total + row.size_bytes, 0);
  return {
    visibleRows,
    hiddenRows,
    visibleBytes: sum(visibleRows),
    hiddenBytes: sum(hiddenRows),
  };
}

/**
 * Narrow rows to the selected risks. An empty selection means "all" and returns
 * the same array, so callers keyed on identity (memos) see no change.
 */
export function filterByRisk(
  rows: CacheTableRow[],
  risks: readonly CacheTableRow["risk"][],
): CacheTableRow[] {
  if (risks.length === 0) return rows;
  return rows.filter((row) => risks.includes(row.risk));
}
