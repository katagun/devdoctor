import { RiskValue, riskLabel } from "@/lib/format";

const variants: Record<RiskValue, string> = {
  safe:
    "bg-gradient-to-b from-badge-safe-from to-badge-safe-to text-risk-safe border-badge-safe-bd",
  reclaimable:
    "bg-gradient-to-b from-badge-reclaim-from to-badge-reclaim-to text-risk-reclaim border-badge-reclaim-bd",
  dangerous:
    "bg-gradient-to-b from-badge-danger-from to-badge-danger-to text-risk-danger border-badge-danger-bd",
};

export function RiskBadge({ risk }: { risk: RiskValue }) {
  return (
    <span
      data-risk={risk}
      className={`inline-block px-1.5 py-0.5 rounded-sm text-[9.5px] font-mono font-medium tracking-wide border ${variants[risk]}`}
    >
      {riskLabel(risk).toUpperCase()}
    </span>
  );
}
