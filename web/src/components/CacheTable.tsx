import { Checkbox } from "./Checkbox";
import { RiskBadge } from "./RiskBadge";
import { humanBytes, staleness, RiskValue } from "@/lib/format";

export interface CacheTableRow {
  id: string;
  provider: string;
  label: string;
  path: string;
  size_bytes: number;
  risk: RiskValue;
  mtime: number | null;
  recipeHint: string;
}

export function CacheTable({
  rows,
  selected,
  onToggle,
}: {
  rows: CacheTableRow[];
  selected: Set<string>;
  onToggle: (id: string, next: boolean) => void;
}) {
  if (rows.length === 0) {
    return (
      <div className="p-8 text-center text-text-dim font-mono text-sm">
        (no entries)
      </div>
    );
  }
  return (
    <div className="font-mono text-[11px]">
      <div className="grid grid-cols-[28px_1.4fr_2fr_0.8fr_0.9fr_0.6fr] gap-2.5 px-4 py-2 border-b border-border text-[9.5px] uppercase tracking-widest text-text-muted">
        <div />
        <div>provider</div>
        <div>path</div>
        <div className="text-right">size</div>
        <div>risk</div>
        <div className="text-right">stale</div>
      </div>
      {rows.map((r) => {
        const isSelected = selected.has(r.id);
        return (
          <div
            key={r.id}
            className="grid grid-cols-[28px_1.4fr_2fr_0.8fr_0.9fr_0.6fr] gap-2.5 px-4 py-[7px] items-center border-b border-[#10151b] hover:bg-bg-elev-1"
          >
            <Checkbox
              checked={isSelected}
              onChange={(next) => onToggle(r.id, next)}
              label={`select ${r.provider} ${r.label}`}
            />
            <div>
              <div className="text-[#9fb5c5] font-medium">{r.provider}</div>
              <div className="text-text-muted text-[9.5px] mt-px">{r.label}</div>
            </div>
            <div className="text-[#7a8b99] truncate" title={r.path}>
              {r.path}
            </div>
            <div className="text-right tabular-nums font-medium">
              {humanBytes(r.size_bytes)}
            </div>
            <div>
              <RiskBadge risk={r.risk} />
            </div>
            <div className="text-right text-text-muted text-[10px]">
              {staleness(r.mtime)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
