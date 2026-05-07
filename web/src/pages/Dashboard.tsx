import { useMemo } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { DiskUsageBar } from "@/components/DiskUsageBar";
import { colorForMosaicTone, MosaicTreemap } from "@/components/MosaicTreemap";
import { useDiskDashboardSummary } from "@/hooks/useDashboard";
import { useMemory, useMemoryProviders } from "@/hooks/useMemory";
import { useProviders } from "@/hooks/useProviders";
import { useScan } from "@/hooks/useScan";
import { useSelectedMemoryProviders } from "@/hooks/useSelectedMemoryProviders";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import { useSettings } from "@/hooks/useSettings";
import {
  buildDiskMosaicItems,
  buildMemoryMosaicItems,
  diskProviderTotals,
  type MosaicTone,
  topMemoryConsumers,
} from "@/lib/dashboard";
import { humanBytes, timeAgo } from "@/lib/format";
import { diskProviderParam, memoryProviderIds } from "@/lib/providerFilters";

export default function Dashboard() {
  const { settings } = useSettings();
  const manualOnly = settings.cadence === "manual";

  const diskProviders = useProviders();
  const selectedDiskProviders = useSelectedProviders();
  const diskProvider = useMemo(
    () => diskProviderParam(diskProviders.data, selectedDiskProviders.disabled),
    [diskProviders.data, selectedDiskProviders.disabled],
  );
  const diskSummary = useDiskDashboardSummary(diskProvider);
  const disk = useScan({
    provider: diskProvider,
    staleTime: 0,
    refetchOnMount: !manualOnly,
  });

  const memoryProviders = useMemoryProviders();
  const selectedMemoryProviders = useSelectedMemoryProviders();
  const selectedMemoryProviderIds = useMemo(
    () => memoryProviderIds(memoryProviders.data, selectedMemoryProviders.disabled),
    [memoryProviders.data, selectedMemoryProviders.disabled],
  );
  const memory = useMemory(selectedMemoryProviderIds);

  const diskRows = disk.data?.rows ?? diskSummary.data?.entries ?? [];
  const diskTotalBytes = disk.data?.totalBytes ?? diskSummary.data?.total_bytes ?? null;
  const diskScannedAt = disk.data?.scannedAt ?? diskSummary.data?.scanned_at ?? null;
  const diskShowingCached = !disk.data && diskSummary.data !== null && diskSummary.data !== undefined;
  const memoryReport = memory.data;
  const diskMosaic = useMemo(() => buildDiskMosaicItems(diskRows, 14), [diskRows]);
  const topMemory = useMemo(
    () => topMemoryConsumers(memoryReport?.consumers ?? [], 5),
    [memoryReport?.consumers],
  );
  const memoryMosaicConsumers = useMemo(
    () => topMemoryConsumers(memoryReport?.consumers ?? [], 16),
    [memoryReport?.consumers],
  );
  const memoryMosaic = useMemo(
    () => buildMemoryMosaicItems(memoryMosaicConsumers, 12),
    [memoryMosaicConsumers],
  );
  const diskProvidersBySize = useMemo(
    () =>
      disk.data
        ? diskProviderTotals(diskRows)
        : (diskSummary.data?.provider_totals.map((total) => ({
            provider: total.provider,
            bytes: total.bytes,
            count: total.count,
          })) ?? []),
    [disk.data, diskRows, diskSummary.data?.provider_totals],
  );
  const topSuggestions = memoryReport?.suggestions.slice(0, 3) ?? [];
  const memorySystem = memoryReport?.system;
  const diskTopProvider = diskProvidersBySize[0] ?? null;
  const isRefreshing = disk.isFetching || memory.isFetching;

  function refresh() {
    void disk.refetch();
    void memory.refetch();
  }

  return (
    <div className="flex flex-col h-screen font-mono">
      <header className="px-4 py-3 border-b border-border flex items-center gap-4 flex-wrap">
        <h1 className="text-text text-[14px] font-medium">Dashboard</h1>
        <StatusLine
          diskAt={diskScannedAt}
          diskCached={diskShowingCached}
          memoryAt={memoryReport?.scanned_at ?? null}
        />
        <button
          type="button"
          onClick={refresh}
          disabled={isRefreshing}
          className={`ml-auto px-2.5 py-[3px] rounded text-[10px] border transition-colors ${
            isRefreshing
              ? "border-border text-text-muted cursor-wait"
              : "border-border text-text-dim hover:text-text hover:border-risk-reclaim"
          }`}
        >
          {isRefreshing ? "refreshing..." : "refresh all"}
        </button>
        <DiskUsageBar />
      </header>

      <main className="flex-1 overflow-auto">
        <div className="p-4 grid gap-4 xl:grid-cols-2">
          <ResourcePanel
            title="Disk reclaim mosaic"
            eyebrow="largest safe and reclaimable entries"
            to="/disk"
            action="open disk scan"
            loading={disk.isLoading && !diskSummary.data}
            error={disk.error}
            refreshing={disk.isFetching && !!diskSummary.data}
            legend={[
              ["reclaimable", "reclaimable"],
              ["safe", "safe"],
              ["other", "other"],
            ]}
            stats={[
              ["reclaimable", diskTotalBytes === null ? "…" : humanBytes(diskTotalBytes)],
              ["entries", diskTotalBytes === null ? "…" : String(diskRows.length)],
              [
                "top provider",
                diskTopProvider
                  ? `${diskTopProvider.provider} · ${humanBytes(diskTopProvider.bytes)}`
                  : disk.isLoading
                    ? "…"
                    : "—",
              ],
            ]}
          >
            <MosaicTreemap
              items={diskMosaic}
              ariaLabel="Disk reclaimable space mosaic"
              emptyLabel="no disk entries to chart"
            />
          </ResourcePanel>

          <ResourcePanel
            title="Memory pressure mosaic"
            eyebrow="largest resident memory consumers"
            to="/memory"
            action="open memory live"
            loading={memory.isLoading}
            error={memory.error}
            legend={[
              ["browser", "browser"],
              ["electron", "electron"],
              ["docker", "docker"],
              ["app", "app"],
              ["process", "process/other"],
            ]}
            stats={[
              [
                "pressure",
                memorySystem ? pressureLabel(memorySystem.pressure) : "…",
              ],
              [
                "available",
                memorySystem ? humanBytes(memorySystem.available_bytes) : "…",
              ],
              [
                "swap",
                !memorySystem
                  ? "…"
                  : memorySystem.swap_used_bytes === null
                  ? "—"
                  : humanBytes(memorySystem.swap_used_bytes),
              ],
            ]}
          >
            <MosaicTreemap
              items={memoryMosaic}
              ariaLabel="Memory usage by provider mosaic"
              emptyLabel="no memory providers to chart"
            />
          </ResourcePanel>
        </div>

        <div className="px-4 pb-4 grid gap-4 xl:grid-cols-3">
          <SummaryList
            title="Disk opportunities"
            emptyLabel="No disk entries reported."
            rows={diskProvidersBySize.slice(0, 5).map((provider) => ({
              id: provider.provider,
              label: provider.provider,
              detail: `${provider.count} entr${provider.count === 1 ? "y" : "ies"}`,
              value: humanBytes(provider.bytes),
            }))}
          />
          <SummaryList
            title="Memory contributors"
            emptyLabel="No memory consumers reported."
            rows={topMemory.map((consumer) => ({
              id: consumer.id,
              label: consumer.name,
              detail: consumer.kind,
              value: humanBytes(consumer.rss_bytes),
            }))}
          />
          <SummaryList
            title="Next actions"
            emptyLabel="No memory suggestions right now."
            rows={topSuggestions.map((suggestion) => ({
              id: suggestion.id,
              label: suggestion.title,
              detail: suggestion.reason,
              value:
                suggestion.estimated_bytes === null
                  ? "unknown"
                  : humanBytes(suggestion.estimated_bytes),
            }))}
          />
        </div>
      </main>
    </div>
  );
}

function StatusLine({
  diskAt,
  diskCached,
  memoryAt,
}: {
  diskAt: string | null;
  diskCached: boolean;
  memoryAt: string | null;
}) {
  return (
    <div className="text-[10.5px] text-text-dim flex items-center gap-3 flex-wrap">
      <span title={diskAt ?? undefined}>
        {diskCached
          ? `disk cached ${diskAt ? timeAgo(diskAt) : "pending"}`
          : `disk ${diskAt ? timeAgo(diskAt) : "pending"}`}
      </span>
      <span className="text-text-muted">/</span>
      <span title={memoryAt ?? undefined}>
        memory {memoryAt ? timeAgo(memoryAt) : "pending"}
      </span>
    </div>
  );
}

function ResourcePanel({
  title,
  eyebrow,
  to,
  action,
  loading,
  error,
  refreshing = false,
  legend,
  stats,
  children,
}: {
  title: string;
  eyebrow: string;
  to: string;
  action: string;
  loading: boolean;
  error: unknown;
  refreshing?: boolean;
  legend?: Array<[MosaicTone, string]>;
  stats: Array<[string, string]>;
  children: ReactNode;
}) {
  return (
    <section className="border border-border bg-bg-elev-1 rounded overflow-hidden min-h-[390px] flex flex-col">
      <div className="px-4 py-3 border-b border-border flex items-center gap-3">
        <div className="min-w-0">
          <div className="text-[9px] uppercase tracking-widest text-text-muted">
            {eyebrow}
          </div>
          <h2 className="text-text text-[13px] font-medium mt-0.5">{title}</h2>
        </div>
        <div className="ml-auto shrink-0 flex items-center gap-2">
          {refreshing && !loading && !error && (
            <span className="px-2 py-[3px] rounded border border-border text-text-muted text-[10px]">
              refreshing…
            </span>
          )}
          <Link
            to={to}
            className="px-2.5 py-[3px] rounded text-[10px] border border-border text-text-dim hover:text-text hover:border-risk-reclaim"
          >
            {action}
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-3 border-b border-border">
        {stats.map(([label, value]) => (
          <div key={label} className="px-4 py-2 border-r border-border last:border-r-0">
            <div className="text-[9px] uppercase tracking-widest text-text-muted">
              {label}
            </div>
            <div className="text-[11px] text-text mt-1 truncate" title={value}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {legend && (
        <div className="px-4 py-2 border-b border-border flex items-center gap-3 flex-wrap text-[9.5px] text-text-muted">
          {legend.map(([tone, label]) => (
            <span key={tone} className="inline-flex items-center gap-1.5">
              <span
                className="w-2 h-2 rounded-sm"
                style={{ background: colorForMosaicTone(tone) }}
              />
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="relative flex-1 min-h-[250px] bg-bg-code">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center text-text-muted text-[11px] animate-pulse">
            loading…
          </div>
        ) : error ? (
          <div className="absolute inset-0 flex items-center justify-center text-risk-danger text-[11px] px-6 text-center">
            {String(error)}
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}

function SummaryList({
  title,
  rows,
  emptyLabel,
}: {
  title: string;
  rows: Array<{ id: string; label: string; detail: string; value: string }>;
  emptyLabel: string;
}) {
  return (
    <section className="border border-border bg-bg-elev-1 rounded overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h2 className="text-text text-[12px] font-medium">{title}</h2>
      </div>
      {rows.length === 0 ? (
        <div className="px-4 py-6 text-text-muted text-[11px]">{emptyLabel}</div>
      ) : (
        <ol>
          {rows.map((row) => (
            <li
              key={row.id}
              className="px-4 py-2.5 border-b border-border-subtle last:border-b-0 flex items-start gap-3"
            >
              <div className="min-w-0 flex-1">
                <div className="text-text text-[11px] truncate" title={row.label}>
                  {row.label}
                </div>
                <div className="text-text-muted text-[10px] truncate" title={row.detail}>
                  {row.detail}
                </div>
              </div>
              <div className="text-text-dim text-[10.5px] tabular-nums shrink-0">
                {row.value}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function pressureLabel(pressure: string): string {
  if (pressure === "critical") return "critical";
  if (pressure === "warn") return "warning";
  if (pressure === "ok") return "ok";
  return "unknown";
}
