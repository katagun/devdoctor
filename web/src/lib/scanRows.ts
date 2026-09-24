import type { CacheTableRow } from "@/components/CacheTable";
import { humanBytes } from "@/lib/format";

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

const SECONDS_PER_DAY = 86_400;

/**
 * Keep rows untouched for at least `minAgeDays`, the web form of the CLI's
 * `--older-than`. A row of unknown age never qualifies: "old enough" has to be
 * shown, not assumed. No minimum returns the same array, for memo identity.
 */
export function filterByAge(
  rows: CacheTableRow[],
  minAgeDays: number,
  nowSecs: number = Date.now() / 1000,
): CacheTableRow[] {
  if (minAgeDays <= 0) return rows;
  const cutoff = nowSecs - minAgeDays * SECONDS_PER_DAY;
  return rows.filter((row) => row.mtime !== null && row.mtime <= cutoff);
}

/** What an unfiltered scan accounts for against the volume's used space (#81). */
export interface ScanCoverage {
  usedBytes: number;
  classifiedBytes: number;
  ratio: number | null;
}

/** "accounts for 128.0G of 400.0G used · 32%", or null when the scan cannot say. */
export function formatCoverage(coverage: ScanCoverage | null | undefined): string | null {
  if (!coverage || coverage.ratio === null) return null;
  const pct = Math.round(coverage.ratio * 100);
  return `accounts for ${humanBytes(coverage.classifiedBytes)} of ${humanBytes(coverage.usedBytes)} used · ${pct}%`;
}
