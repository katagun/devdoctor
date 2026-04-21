import { useProviders } from "@/hooks/useProviders";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import { RiskBadge } from "@/components/RiskBadge";

export default function Providers() {
  const { data, isLoading, error } = useProviders();
  const { isEnabled, setEnabled } = useSelectedProviders();
  if (isLoading)
    return <div className="p-8 text-text-muted font-mono text-sm">loading…</div>;
  if (error)
    return <div className="p-8 text-risk-danger font-mono text-sm">{String(error)}</div>;
  const providers = data ?? [];
  const enabledCount = providers.filter((p) => isEnabled(p.name)).length;

  return (
    <div className="font-mono text-[11px] p-6">
      <div className="mb-4 text-text-dim text-[11px]">
        <b className="text-text">{enabledCount}</b> of{" "}
        <b className="text-text">{providers.length}</b> providers enabled — toggle off to exclude a
        provider from scans. Preference is stored locally.
      </div>
      <div className="grid grid-cols-[60px_1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 text-[9.5px] uppercase tracking-widest text-text-muted border-b border-border">
        <div>enabled</div>
        <div>name</div>
        <div>risk</div>
        <div>platforms</div>
        <div>available</div>
        <div>required binary</div>
      </div>
      {providers.map((p) => {
        const on = isEnabled(p.name);
        return (
          <div
            key={p.name}
            className="grid grid-cols-[60px_1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 items-center border-b border-border-subtle hover:bg-bg-elev-1"
          >
            <button
              type="button"
              onClick={() => setEnabled(p.name, !on)}
              aria-pressed={on}
              aria-label={`Toggle ${p.name}`}
              className={`w-[30px] h-[16px] rounded-full relative transition-colors ${
                on ? "bg-[#2a7f55]" : "bg-bg-control-off"
              }`}
            >
              <span
                className={`absolute top-[2px] w-[12px] h-[12px] rounded-full bg-white transition-all ${
                  on ? "right-[2px]" : "left-[2px] bg-text-muted"
                }`}
              />
            </button>
            <div>
              <div className={`font-medium ${on ? "text-text" : "text-text-muted"}`}>{p.name}</div>
              <div className="text-text-muted text-[10px] mt-px">{p.description}</div>
            </div>
            <div>
              <RiskBadge risk={p.risk} />
            </div>
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
        );
      })}
    </div>
  );
}
