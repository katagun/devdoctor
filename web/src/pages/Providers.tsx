import { useMemo, useState } from "react";
import { useProviders } from "@/hooks/useProviders";
import { useSelectedProviders } from "@/hooks/useSelectedProviders";
import { RiskBadge } from "@/components/RiskBadge";
import { DiskUsageBar } from "@/components/DiskUsageBar";
import { ProviderIcon } from "@/components/ProviderIcon";

export default function Providers() {
  const { data, isLoading, error } = useProviders();
  const { isEnabled, setEnabled, setMany } = useSelectedProviders();
  const [query, setQuery] = useState("");

  const providers = useMemo(() => data ?? [], [data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return providers;
    return providers.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q),
    );
  }, [providers, query]);

  const enabledCount = providers.filter((p) => isEnabled(p.name)).length;
  const allOn = providers.length > 0 && enabledCount === providers.length;
  const allOff = enabledCount === 0;
  const mixed = !allOn && !allOff;

  function flipMaster() {
    // Binary: anything enabled → disable all; none enabled → enable all.
    // Mixed collapses to "disable all" on click, matching the user's
    // "slider to unselect all" intent.
    const names = providers.map((p) => p.name);
    setMany(names, allOff);
  }

  if (isLoading)
    return <div className="p-8 text-text-muted font-mono text-sm">loading…</div>;
  if (error)
    return <div className="p-8 text-risk-danger font-mono text-sm">{String(error)}</div>;

  return (
    <div className="font-mono text-[11px]">
      <header className="px-6 pt-6 pb-3 flex items-center justify-between gap-4 flex-wrap">
        <label className="relative block w-full max-w-[360px] flex-1 min-w-[260px]">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search providers by name or description…"
            className="w-full bg-bg-elev-1 border border-border rounded pl-7 pr-8 py-1.5 text-[11px] text-text placeholder:text-text-muted focus:outline-none focus:border-risk-reclaim"
          />
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none">
            ⌕
          </span>
          {query && (
            <button
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text"
            >
              ✕
            </button>
          )}
        </label>

        <div className="text-text-dim text-[11px] tabular-nums">
          <b className="text-text">{enabledCount}</b> of{" "}
          <b className="text-text">{providers.length}</b> enabled
          {query && (
            <span className="text-text-muted">
              {" "}
              · {filtered.length} match{filtered.length === 1 ? "" : "es"}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-text-muted text-[10px]">
            {allOff ? "enable all" : "disable all"}
          </span>
          <button
            type="button"
            onClick={flipMaster}
            aria-pressed={!allOff}
            aria-label={allOff ? "Enable all providers" : "Disable all providers"}
            disabled={providers.length === 0}
            className={`w-[36px] h-[18px] rounded-full relative transition-colors ${
              allOn ? "bg-[#2a7f55]" : mixed ? "bg-[#2a7f55]/50" : "bg-bg-control-off"
            }`}
          >
            <span
              className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all ${
                allOff ? "left-[2px] bg-text-muted" : "right-[2px]"
              }`}
            />
          </button>
        </div>
        <DiskUsageBar />
      </header>

      <div className="px-6 pb-3 text-text-muted text-[10px]">
        Toggle off to exclude a provider from scans. Preference is stored locally.
      </div>

      <div className="px-6">
        <div className="grid grid-cols-[60px_20px_1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 text-[9.5px] uppercase tracking-widest text-text-muted border-b border-border">
          <div>enabled</div>
          <div aria-hidden="true" />
          <div>name</div>
          <div>risk</div>
          <div>platforms</div>
          <div>available</div>
          <div>required binary</div>
        </div>
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-text-dim">
            {query ? (
              <>
                No providers match <span className="text-text">&ldquo;{query}&rdquo;</span>.
              </>
            ) : (
              "No providers."
            )}
          </div>
        ) : (
          filtered.map((p) => {
            const on = isEnabled(p.name);
            return (
              <div
                key={p.name}
                className="grid grid-cols-[60px_20px_1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 items-center border-b border-border-subtle hover:bg-bg-elev-1"
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
                <div className="flex items-center justify-center">
                  <ProviderIcon
                    slug={p.name}
                    size={16}
                    className={on ? "text-text" : "text-text-muted"}
                  />
                </div>
                <div>
                  <div className={`font-medium ${on ? "text-text" : "text-text-muted"}`}>
                    <Highlight text={p.name} query={query} />
                  </div>
                  <div className="text-text-muted text-[10px] mt-px">
                    <Highlight text={p.description} query={query} />
                  </div>
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
          })
        )}
      </div>
    </div>
  );
}

// Highlights the first case-insensitive match of `query` in `text`.
function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-risk-reclaim/30 text-text rounded-[2px] px-[1px]">
        {text.slice(idx, idx + q.length)}
      </mark>
      {text.slice(idx + q.length)}
    </>
  );
}
