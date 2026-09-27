import type { QueryClient } from "@tanstack/react-query";
import type { CacheTableRow } from "@/components/CacheTable";
import type { CleanupResult } from "@/components/CleanupWizard/CleanupWizardState";
import type { Removal } from "@/lib/scanRows";

const REMOVALS_KEY = ["cleanup-removals"] as const;

/** What a cleanup removed, or null when it removed nothing. */
export function removalFrom(
  results: CleanupResult[],
  entries: CacheTableRow[],
  at: number,
): Removal | null {
  const okIds = results.filter((result) => result.status === "ok").map((result) => result.entry_id);
  if (okIds.length === 0) return null;
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  // "ok" only means every action exited 0. A prune-style command (pnpm store
  // prune, conda clean --packages) or a Time Machine "all but newest" bundle
  // can leave the entry in place — those carry reclaimable_bytes: null. Keep
  // that row in the cached scans; only a later scan can say what remains.
  const ids = okIds.filter((id) => byId.get(id)?.reclaimable_bytes !== null);
  const removed = new Set(ids);
  const paths = entries
    .filter((entry) => removed.has(entry.id) && entry.path.startsWith("/"))
    .map((entry) => entry.path);
  return { ids, paths, at };
}

/** Kept for the page's lifetime: nothing observes the key, so it must never be collected. */
export function recordRemoval(client: QueryClient, removal: Removal): void {
  client.setQueryDefaults(REMOVALS_KEY, { gcTime: Number.POSITIVE_INFINITY });
  client.setQueryData<Removal[]>(REMOVALS_KEY, (old) => [...(old ?? []), removal]);
}

/** The removals after a scan began: that scan may still list what they deleted. */
export function removalsSince(client: QueryClient, startedAt: string | null): Removal[] {
  const all = client.getQueryData<Removal[]>(REMOVALS_KEY) ?? [];
  const started = startedAt === null ? Number.NaN : Date.parse(startedAt);
  if (Number.isNaN(started)) return all;
  return all.filter((removal) => removal.at > started);
}
