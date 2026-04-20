import { useMemo, useState } from "react";
import { CacheTable } from "@/components/CacheTable";
import { TopStats } from "@/components/TopStats";
import { useScan } from "@/hooks/useScan";
import { humanBytes, RiskValue } from "@/lib/format";

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

  const { data, isLoading, error } = useScan({ risk: riskParam });
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const rows = data?.rows ?? [];
  const totalSelected = useMemo(
    () => rows.filter((r) => selected.has(r.id)).reduce((a, b) => a + b.size_bytes, 0),
    [rows, selected],
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
        cacheCount={rows.length}
        diskUsedPct={null}
      />
      <div className="px-4 py-2.5 border-b border-border flex gap-2 items-center">
        {RISK_CHIPS.map((chip) => (
          <button
            key={chip.key}
            onClick={() => setActiveChip(chip.key)}
            className={`px-2.5 py-[3px] rounded text-[10px] font-mono border ${
              activeChip === chip.key
                ? "border-[#2a7f55] bg-[#13241a] text-risk-safe"
                : "border-border bg-bg-elev-1 text-text-dim hover:text-text"
            }`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto">
        {error && <div className="p-8 text-risk-danger font-mono text-sm">Error loading scan: {String(error)}</div>}
        {isLoading && (
          <div className="p-8 text-text-muted font-mono text-sm animate-pulse">scanning…</div>
        )}
        {!isLoading && !error && (
          <CacheTable rows={rows} selected={selected} onToggle={toggle} />
        )}
      </div>

      <div className="px-4 py-3 bg-bg-elev-1 border-t border-border flex justify-between items-center">
        <span className="font-mono text-[11px] text-text-dim">
          {selected.size} selected · <b className="text-text">{humanBytes(totalSelected)}</b>
        </span>
        <button
          disabled={selected.size === 0}
          className="bg-gradient-to-b from-[#3aa670] to-[#2a7f55] text-[#e8fff3] px-4 py-1.5 rounded border border-[#3aa670] font-medium text-[11px] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          ▸ clean up {selected.size > 0 ? `${selected.size} items` : ""}
        </button>
      </div>
    </div>
  );
}
