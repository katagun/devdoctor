import { AlertTriangle, Play } from "lucide-react";
import { NavIcon } from "@/components/NavIcon";
import { RiskBadge } from "@/components/RiskBadge";
import { ProviderIcon } from "@/components/ProviderIcon";
import { humanBytes, parseRecipeHint } from "@/lib/format";
import { useWizardContext } from "./CleanupWizardState";

export function ReviewStep() {
  const { state, toggleEnabled, startJob } = useWizardContext();
  const enabledTotal = state.entries
    .filter((e) => state.enabled.has(e.id))
    .reduce((a, b) => a + b.size_bytes, 0);

  return (
    <div className="flex flex-col h-full font-mono text-[11px]">
      <div className="flex-1 overflow-auto p-4 space-y-2">
        {state.entries.map((e) => {
          const on = state.enabled.has(e.id);
          return (
            <div
              key={e.id}
              className={`border border-border rounded p-3 bg-bg-elev-1 ${
                e.risk === "dangerous" ? "border-border-danger" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-text font-medium text-[12px] flex items-center gap-1">
                    <ProviderIcon slug={e.provider} size={12} className="shrink-0" />
                    <span>
                      {e.provider} / {e.label}
                    </span>
                  </div>
                  <div className="text-text-muted mt-0.5">{e.path}</div>
                </div>
                <div className="flex items-center gap-3">
                  <RiskBadge risk={e.risk} />
                  <span className="font-medium text-[12px]">{humanBytes(e.size_bytes)}</span>
                  <button
                    onClick={() => toggleEnabled(e.id, !on)}
                    className={`w-[30px] h-[16px] rounded-full relative ${
                      on ? "bg-btn-primary-to" : "bg-bg-control-off"
                    }`}
                  >
                    <span
                      className={`absolute top-[2px] w-[12px] h-[12px] rounded-full bg-white transition-all ${
                        on ? "right-[2px]" : "left-[2px] bg-text-muted"
                      }`}
                    />
                  </button>
                </div>
              </div>
              {(() => {
                const hint = parseRecipeHint(e.recipeHint);
                if (hint.kind === "command") {
                  return (
                    <div className="bg-bg-code border border-bg-safe-tint rounded px-2.5 py-1.5 mt-2 text-risk-safe text-[10.5px] break-all">
                      <span className="inline-flex items-center gap-1.5">
                        <NavIcon icon={Play} size={12} />
                        <span>{hint.text}</span>
                      </span>
                    </div>
                  );
                }
                return (
                  <div className="bg-bg-code border border-border rounded px-3 py-2 mt-2 text-[10.5px] leading-relaxed">
                    <div className="text-risk-reclaim text-[9px] uppercase tracking-widest mb-1.5">
                      advice
                    </div>
                    <ul className="space-y-1 text-text-dim">
                      {hint.sentences.map((s, i) => (
                        <li key={i} className="flex gap-2">
                          <span className="text-text-muted shrink-0">·</span>
                          <span className="break-words">{s}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })()}
              {e.risk === "dangerous" && !on && (
                <div className="text-risk-danger text-[10px] mt-1.5 pl-2 border-l-2 border-risk-danger">
                  <span className="inline-flex items-center gap-1.5">
                    <NavIcon icon={AlertTriangle} size={12} />
                    <span>
                      Dangerous providers are off by default. Enable only if you understand the consequence.
                    </span>
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="px-4 py-3 bg-bg-elev-2 border-t border-border flex items-center justify-between">
        <span className="text-text-dim">
          <b className="text-text">
            {state.enabled.size} of {state.entries.length}
          </b>{" "}
          enabled · <b className="text-risk-safe">{humanBytes(enabledTotal)}</b> will be freed
        </span>
        <button
          onClick={startJob}
          disabled={state.enabled.size === 0}
          className="bg-gradient-to-b from-btn-primary-from to-btn-primary-to text-btn-primary-fg px-4 py-1.5 rounded border border-btn-primary-bd font-medium text-[11px] disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-1.5">
            <NavIcon icon={Play} size={12} />
            execute
          </span>
        </button>
      </div>
    </div>
  );
}
