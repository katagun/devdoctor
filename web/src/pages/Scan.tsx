import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CacheTable } from "@/components/CacheTable";
import { CleanupWizard } from "@/components/CleanupWizard";
import { ColumnsPicker } from "@/components/ColumnsPicker";
import { DiskPageHeader } from "@/components/DiskPageHeader";
import { DomainToolTabs } from "@/components/DomainToolTabs";
import { SparklineBar } from "@/components/SparklineBar";
import { useScan } from "@/hooks/useScan";
import { useProviders } from "@/hooks/useProviders";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import { cadenceMs, useSettings } from "@/hooks/useSettings";
import { useScanETA } from "@/hooks/useScanETA";
import { formatMs, humanBytes, RiskValue, timeAgo } from "@/lib/format";

const RISK_CHIPS: Array<{ key: string; label: string; risks: RiskValue[] }> = [
  { key: "all", label: "all", risks: [] },
  { key: "safe", label: "safe", risks: ["safe"] },
  { key: "reclaim", label: "reclaim", risks: ["reclaimable"] },
  { key: "danger", label: "danger", risks: ["dangerous"] },
];

export default function Scan() {
  const [activeChip, setActiveChip] = useState<string>("all");
  const riskParam =
    activeChip === "all" ? undefined : RISK_CHIPS.find((c) => c.key === activeChip)?.risks.join(",");

  const { data: providers } = useProviders();
  const { disabled } = useSelectedProviders();
  const providerParam = useMemo(() => {
    if (!providers || disabled.size === 0) return undefined;
    const enabled = providers.filter((p) => !disabled.has(p.name)).map((p) => p.name);
    return enabled.length ? enabled.join(",") : "__diskdoctor_nothing_enabled__";
  }, [providers, disabled]);

  const { settings } = useSettings();
  const staleTime = cadenceMs(settings.cadence);
  const manualOnly = settings.cadence === "manual";

  const { data, isLoading, error, refetch, isFetching } = useScan({
    risk: riskParam,
    provider: providerParam,
    staleTime,
    refetchOnMount: !manualOnly,
    explicit: true,
    // Cadence as the auto-snapshot rate limit. Without this, every filter
    // chip change writes a new auto-snapshot because the queryKey changes
    // (staleTime can't suppress fetches against a fresh key). The server
    // honours the interval and quietly skips writes that fall inside it.
    snapshotMinIntervalMs: staleTime,
  });

  const eta = useScanETA();

  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [wizardOpen, setWizardOpen] = useState(false);
  const [showHiddenRows, setShowHiddenRows] = useState(false);

  const allRows = data?.rows ?? [];
  const { visibleRows, hiddenRows, hiddenBytes, visibleBytes } = useMemo(() => {
    const threshold = settings.minSizeBytes;
    if (threshold <= 0) {
      const totalBytes = allRows.reduce((a, b) => a + b.size_bytes, 0);
      return { visibleRows: allRows, hiddenRows: [], hiddenBytes: 0, visibleBytes: totalBytes };
    }
    const visible = allRows.filter((r) => r.size_bytes >= threshold);
    const hidden = allRows.filter((r) => r.size_bytes < threshold);
    const hBytes = hidden.reduce((a, b) => a + b.size_bytes, 0);
    const vBytes = visible.reduce((a, b) => a + b.size_bytes, 0);
    return { visibleRows: visible, hiddenRows: hidden, hiddenBytes: hBytes, visibleBytes: vBytes };
  }, [allRows, settings.minSizeBytes]);

  const selectedRows = visibleRows.filter((r) => selected.has(r.id));
  const totalSelected = useMemo(
    () => selectedRows.reduce((a, b) => a + b.size_bytes, 0),
    [selectedRows],
  );

  function toggle(id: string, next: boolean) {
    setSelected((prev) => {
      const copy = new Set(prev);
      if (next) copy.add(id);
      else copy.delete(id);
      return copy;
    });
  }

  return (
    <div className="flex flex-col h-screen">
      <DiskPageHeader>
        <span>
          <b className="text-text">{humanBytes(data?.totalBytes ?? 0)}</b> reclaimable
        </span>
        <SparklineBar heights={[20, 35, 45, 58, 70, 82, 92, 85]} />
        <span>
          <b className="text-text">{allRows.length}</b> caches
        </span>
      </DiskPageHeader>
      <DomainToolTabs domain="disk" />
      <div className="px-4 py-2.5 border-b border-border flex gap-2 items-center flex-wrap">
        {RISK_CHIPS.map((chip) => (
          <button
            key={chip.key}
            onClick={() => setActiveChip(chip.key)}
            className={`px-2.5 py-[3px] rounded text-[10px] font-mono border ${
              activeChip === chip.key
                ? "border-btn-primary-bd bg-bg-safe-tint text-risk-safe"
                : "border-border bg-bg-elev-1 text-text-dim hover:text-text"
            }`}
          >
            {chip.label}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-3 font-mono text-[10px] text-text-dim">
          <ColumnsPicker />
          {data?.scannedAt && (
            <span title={data.scannedAt}>
              scanned {timeAgo(data.scannedAt)}
            </span>
          )}
          <button
            onClick={() => refetch().then(() => queryClient.invalidateQueries({ queryKey: ["disk-usage"] }))}
            disabled={isFetching}
            className={`px-2.5 py-[3px] rounded text-[10px] font-mono border transition-colors ${
              isFetching
                ? "border-border text-text-muted cursor-wait"
                : "border-border text-text-dim hover:text-text hover:border-risk-reclaim"
            }`}
          >
            {isFetching ? (
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-risk-reclaim animate-pulse" />
                rescanning…
                {eta && eta.etaMs !== null && <> · ~{formatMs(eta.etaMs)}</>}
              </span>
            ) : (
              "↻ rescan now"
            )}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {error && <div className="p-8 text-risk-danger font-mono text-sm">Error loading scan: {String(error)}</div>}
        {isLoading && (
          <div className="p-8 text-text-muted font-mono text-sm animate-pulse">
            scanning…
            {eta && eta.etaMs !== null && <> · ~{formatMs(eta.etaMs)}</>}
          </div>
        )}
        {!isLoading && !error && (
          <CacheTable
            rows={showHiddenRows ? allRows : visibleRows}
            selected={selected}
            onToggle={toggle}
            density={settings.density}
          />
        )}
      </div>

      {/* Pinned totals row — always visible above the action bar, independent of scroll. */}
      <div className="px-4 py-2 border-t border-border bg-bg-elev-1 font-mono text-[11px] flex items-center justify-between gap-4 shrink-0">
        <span className="text-text-dim">
          <b className="text-text">
            {showHiddenRows ? allRows.length : visibleRows.length}
          </b>{" "}
          shown ·{" "}
          <b className="text-text tabular-nums">
            {humanBytes(showHiddenRows ? visibleBytes + hiddenBytes : visibleBytes)}
          </b>
          {hiddenRows.length > 0 && (
            <>
              <span className="text-text-muted"> · </span>
              <button
                type="button"
                onClick={() => setShowHiddenRows((s) => !s)}
                aria-expanded={showHiddenRows}
                className="text-text-muted hover:text-text underline-offset-2 hover:underline"
              >
                {showHiddenRows ? "▾" : "▸"} +{hiddenRows.length} under{" "}
                {humanBytes(settings.minSizeBytes)} totalling{" "}
                <span className="tabular-nums">{humanBytes(hiddenBytes)}</span>
              </button>
            </>
          )}
        </span>
      </div>

      <div className="px-4 py-3 bg-bg-elev-1 border-t border-border flex justify-between items-center">
        <span className="font-mono text-[11px] text-text-dim">
          {selectedRows.length} selected ·{" "}
          <b className="text-text">{humanBytes(totalSelected)}</b>
        </span>
        <button
          disabled={selectedRows.length === 0}
          onClick={() => setWizardOpen(true)}
          className={
            selectedRows.length === 0
              ? "bg-bg-elev-2 text-text-muted px-4 py-1.5 rounded border border-border font-medium text-[11px] cursor-not-allowed"
              : "bg-gradient-to-b from-btn-primary-from to-btn-primary-to text-btn-primary-fg px-4 py-1.5 rounded border border-btn-primary-bd font-medium text-[11px]"
          }
        >
          ▸ clean up {selectedRows.length > 0 ? `${selectedRows.length} items` : ""}
        </button>
      </div>
      {wizardOpen && (
        <CleanupWizard
          entries={selectedRows}
          onClose={() => setWizardOpen(false)}
          onSuccess={(results) => {
            // Drop only the entries that actually got cleaned so a retry of
            // failed/skipped ones keeps its selection intact.
            const cleaned = new Set(
              results.filter((r) => r.status === "ok").map((r) => r.entry_id),
            );
            if (cleaned.size === 0) return;
            setSelected((prev) => {
              const next = new Set(prev);
              for (const id of cleaned) next.delete(id);
              return next;
            });
          }}
        />
      )}
    </div>
  );
}
