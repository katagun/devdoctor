import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CacheTable } from "@/components/CacheTable";
import { CleanupWizard } from "@/components/CleanupWizard";
import { ColumnsPicker } from "@/components/ColumnsPicker";
import { TopStats } from "@/components/TopStats";
import { useScan } from "@/hooks/useScan";
import { useProviders } from "@/hooks/useProviders";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import { cadenceMs, useSettings } from "@/hooks/useSettings";
import { humanBytes, RiskValue, timeAgo } from "@/lib/format";

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
  });

  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [wizardOpen, setWizardOpen] = useState(false);

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
      <TopStats
        reclaimable={data?.totalBytes ?? 0}
        cacheCount={allRows.length}
      />
      <div className="px-4 py-2.5 border-b border-border flex gap-2 items-center flex-wrap">
        {RISK_CHIPS.map((chip) => (
          <button
            key={chip.key}
            onClick={() => setActiveChip(chip.key)}
            className={`px-2.5 py-[3px] rounded text-[10px] font-mono border ${
              activeChip === chip.key
                ? "border-[#2a7f55] bg-bg-safe-tint text-risk-safe"
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
          <div className="p-8 text-text-muted font-mono text-sm animate-pulse">scanning…</div>
        )}
        {!isLoading && !error && (
          <CacheTable
            rows={visibleRows}
            selected={selected}
            onToggle={toggle}
            density={settings.density}
          />
        )}
      </div>

      {/* Pinned totals row — always visible above the action bar, independent of scroll. */}
      <div className="px-4 py-2 border-t border-border bg-bg-elev-1 font-mono text-[11px] flex items-center justify-between gap-4 shrink-0">
        <span className="text-text-dim">
          <b className="text-text">{visibleRows.length}</b> shown ·{" "}
          <b className="text-text tabular-nums">{humanBytes(visibleBytes)}</b>
          {hiddenRows.length > 0 && (
            <>
              <span className="text-text-muted"> · </span>
              <span className="text-text-muted">
                +{hiddenRows.length} under {humanBytes(settings.minSizeBytes)}
                {" "}totalling{" "}
                <span className="tabular-nums">{humanBytes(hiddenBytes)}</span>
              </span>
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
          className="bg-gradient-to-b from-[#3aa670] to-[#2a7f55] text-[#e8fff3] px-4 py-1.5 rounded border border-[#3aa670] font-medium text-[11px] disabled:opacity-50 disabled:cursor-not-allowed"
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
