import { useDiskUsage } from "@/hooks/useDiskUsage";
import { humanBytes } from "@/lib/format";
import { DISK_LABEL } from "@/lib/resourceLabels";

// Threshold bands for the fill color. <10% free = red, <25% = amber, else green.
const LOW = 0.1;
const MED = 0.25;

function tone(freeRatio: number): { fill: string; text: string } {
  if (freeRatio < LOW) return { fill: "var(--risk-danger)", text: "var(--risk-danger)" };
  if (freeRatio < MED) return { fill: "var(--risk-reclaim)", text: "var(--text-accent)" };
  return { fill: "var(--risk-safe)", text: "var(--text-dim)" };
}

export function DiskUsageBar() {
  const { data, isError } = useDiskUsage();
  if (isError) {
    return (
      <div className="text-[10px] font-mono text-text-muted" title={`${DISK_LABEL} usage lookup failed`}>
        {DISK_LABEL} · —
      </div>
    );
  }
  if (!data) {
    return <div className="text-[10px] font-mono text-text-muted">{DISK_LABEL} · …</div>;
  }
  const { total_bytes, free_bytes, used_bytes, mount } = data;
  const freeRatio = total_bytes > 0 ? free_bytes / total_bytes : 0;
  const usedPct = Math.round((used_bytes / total_bytes) * 100);
  const freePct = Math.round(freeRatio * 100);
  const t = tone(freeRatio);

  return (
    <div
      className="flex items-center gap-2.5 font-mono text-[10.5px] select-none"
      title={`${mount}: ${humanBytes(used_bytes)} used of ${humanBytes(total_bytes)} (${usedPct}% full)`}
    >
      <span className="text-text-muted uppercase tracking-widest text-[9px]">{DISK_LABEL}</span>
      <div
        className="relative h-[6px] w-[120px] rounded-sm overflow-hidden"
        style={{ background: "var(--bg-control-off)" }}
      >
        <div
          className="absolute inset-y-0 left-0"
          style={{ width: `${usedPct}%`, background: t.fill, opacity: 0.85 }}
        />
      </div>
      <span style={{ color: t.text }}>
        {humanBytes(free_bytes)} <span className="text-text-muted">free</span>
      </span>
      <span className="text-text-muted">/ {humanBytes(total_bytes)}</span>
      <span className="text-text-muted">· {freePct}% free</span>
    </div>
  );
}
