import type { DiffReport } from "@/hooks/useDiff";
import { humanBytes } from "@/lib/format";

export function DiffTable({ diff }: { diff: DiffReport }) {
  return (
    <div className="font-mono text-[11px]">
      <div className="grid grid-cols-[1.5fr_1fr_1fr_1fr_0.8fr] gap-3 px-3 py-2 border-b border-border text-[9.5px] uppercase tracking-widest text-text-muted">
        <div>provider</div>
        <div className="text-right">before</div>
        <div className="text-right">after</div>
        <div className="text-right">Δ bytes</div>
        <div className="text-right">Δ %</div>
      </div>
      {diff.rows.map((r) => {
        const color = r.delta_bytes < 0 ? "text-risk-safe" : r.delta_bytes > 0 ? "text-risk-danger" : "text-text-dim";
        return (
          <div
            key={r.provider}
            className="grid grid-cols-[1.5fr_1fr_1fr_1fr_0.8fr] gap-3 px-3 py-1.5 items-center border-b border-[#10151b]"
          >
            <div className="text-[#9fb5c5]">{r.provider}</div>
            <div className="text-right tabular-nums">{humanBytes(r.before_bytes)}</div>
            <div className="text-right tabular-nums">{humanBytes(r.after_bytes)}</div>
            <div className={`text-right tabular-nums ${color}`}>
              {r.delta_bytes > 0 ? "+" : ""}
              {humanBytes(r.delta_bytes)}
            </div>
            <div className={`text-right tabular-nums ${color}`}>
              {r.delta_pct > 0 ? "+" : ""}
              {r.delta_pct.toFixed(1)}%
            </div>
          </div>
        );
      })}
    </div>
  );
}
