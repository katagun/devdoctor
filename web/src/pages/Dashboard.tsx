import { useMemo } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { DiskUsageBar } from "@/components/DiskUsageBar";
import { MosaicTreemap } from "@/components/MosaicTreemap";
import { useMemory, useMemoryProviders } from "@/hooks/useMemory";
import { useProviders } from "@/hooks/useProviders";
import { useScan } from "@/hooks/useScan";
import { useSelectedMemoryProviders } from "@/hooks/useSelectedMemoryProviders";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import { cadenceMs, useSettings } from "@/hooks/useSettings";
import {
  buildDiskMosaicItems,
  buildMemoryMosaicItems,
  diskProviderTotals,
  topMemoryConsumers,
} from "@/lib/dashboard";
import { humanBytes, timeAgo } from "@/lib/format";
import { diskProviderParam, memoryProviderIds } from "@/lib/providerFilters";

export default function Dashboard() {
  const { settings } = useSettings();
  const staleTime = cadenceMs(settings.cadence);
  const manualOnly = settings.cadence === "manual";

  const diskProviders = useProviders();
  const selectedDiskProviders = useSelectedProviders();
  const diskProvider = useMemo(
    () => diskProviderParam(diskProviders.data, selectedDiskProviders.disabled),
    [diskProviders.data, selectedDiskProviders.disabled],
  );
  const disk = useScan({
    provider: diskProvider,
    staleTime,
    refetchOnMount: !manualOnly,
  });

  const memoryProviders = useMemoryProviders();
  const selectedMemoryProviders = useSelectedMemoryProviders();
  const selectedMemoryProviderIds = useMemo(
    () => memoryProviderIds(memoryProviders.data, selectedMemoryProviders.disabled),
    [memoryProviders.data, selectedMemoryProviders.disabled],
  );
  const memory = useMemory(selectedMemoryProviderIds);

  const diskRows = disk.data?.rows ?? [];
  const memoryReport = memory.data;
  const diskMosaic = useMemo(() => buildDiskMosaicItems(diskRows, 14), [diskRows]);
  const memoryMosaic = useMemo(
    () => buildMemoryMosaicItems(memoryReport?.provider_totals ?? [], 10),
    [memoryReport?.provider_totals],
  );
  const diskProvidersBySize = useMemo(() => diskProviderTotals(diskRows), [diskRows]);
  const topMemory = useMemo(
    () => topMemoryConsumers(memoryReport?.consumers ?? [], 5),
    [memoryReport?.consumers],
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
          diskAt={disk.data?.scannedAt ?? null}
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
            loading={disk.isLoading}
            error={disk.error}
            stats={[
              ["reclaimable", disk.data ? humanBytes(disk.data.totalBytes) : "…"],
              ["entries", disk.data ? String(diskRows.length) : "…"],
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
            eyebrow="resident memory by provider"
            to="/memory"
            action="open memory live"
            loading={memory.isLoading}
            error={memory.error}
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
  memoryAt,
}: {
  diskAt: string | null;
  memoryAt: string | null;
}) {
  return (
    <div className="text-[10.5px] text-text-dim flex items-center gap-3 flex-wrap">
      <span title={diskAt ?? undefined}>disk {diskAt ? timeAgo(diskAt) : "pending"}</span>
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
  stats,
  children,
}: {
  title: string;
  eyebrow: string;
  to: string;
  action: string;
  loading: boolean;
  error: unknown;
  stats: Array<[string, string]>;
  children: ReactNode;
}) {
  return (
    <section className="border border-border bg-bg-elev-1 rounded overflow-hidden min-h-[470px] flex flex-col">
      <div className="px-4 py-3 border-b border-border flex items-center gap-3">
        <div className="min-w-0">
          <div className="text-[9px] uppercase tracking-widest text-text-muted">
            {eyebrow}
          </div>
          <h2 className="text-text text-[13px] font-medium mt-0.5">{title}</h2>
        </div>
        <Link
          to={to}
          className="ml-auto shrink-0 px-2.5 py-[3px] rounded text-[10px] border border-border text-text-dim hover:text-text hover:border-risk-reclaim"
        >
          {action}
        </Link>
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

      <div className="relative flex-1 min-h-[330px] bg-bg-code">
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
