import { RiskValue, riskLabel } from "@/lib/format";

const variants: Record<RiskValue, string> = {
  safe:
    "bg-gradient-to-b from-[#163a28] to-[#0f2a1d] text-risk-safe border-[#2a7f55]",
  reclaimable:
    "bg-gradient-to-b from-[#2a1f4a] to-[#1f1838] text-risk-reclaim border-[#5a3fa0]",
  dangerous:
    "bg-gradient-to-b from-[#3a1520] to-[#2a0f17] text-risk-danger border-border-danger",
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
