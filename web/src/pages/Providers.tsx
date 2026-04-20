import { useProviders } from "@/hooks/useProviders";
import { RiskBadge } from "@/components/RiskBadge";

export default function Providers() {
  const { data, isLoading, error } = useProviders();
  if (isLoading)
    return <div className="p-8 text-text-muted font-mono text-sm">loading…</div>;
  if (error)
    return <div className="p-8 text-risk-danger font-mono text-sm">{String(error)}</div>;
  const providers = data ?? [];

  return (
    <div className="font-mono text-[11px] p-6">
      <div className="grid grid-cols-[1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 text-[9.5px] uppercase tracking-widest text-text-muted border-b border-border">
        <div>name</div>
        <div>risk</div>
        <div>platforms</div>
        <div>available</div>
        <div>required binary</div>
      </div>
      {providers.map((p) => (
        <div
          key={p.name}
          className="grid grid-cols-[1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 items-center border-b border-[#10151b] hover:bg-bg-elev-1"
        >
          <div>
            <div className="text-text font-medium">{p.name}</div>
            <div className="text-text-muted text-[10px] mt-px">{p.description}</div>
          </div>
          <div><RiskBadge risk={p.risk} /></div>
          <div className="text-text-dim">{p.platforms.join(", ")}</div>
          <div>
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                p.available ? "bg-risk-safe shadow-[0_0_6px_var(--risk-safe)]" : "bg-text-muted"
              }`}
            />
            <span className="ml-2 text-text-dim">{p.available ? "yes" : "no"}</span>
          </div>
          <div className="text-text-muted">{p.required_binary ?? "—"}</div>
        </div>
      ))}
    </div>
  );
}
