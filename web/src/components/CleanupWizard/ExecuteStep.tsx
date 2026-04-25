import { useWizardContext } from "./CleanupWizardState";
import { humanBytes } from "@/lib/format";

export function ExecuteStep() {
  const { state, answerPrompt, confirm, cancel } = useWizardContext();
  const progressList = state.entries.map((e) =>
    state.progress[e.id] ?? { entry_id: e.id, status: "pending", freed_bytes: 0, consoleLines: [] },
  );
  const doneCount = progressList.filter((p) => p.status !== "pending" && p.status !== "running").length;
  const activePrompt = state.pendingPrompts[0] ?? null;
  const approvedTotal = state.entries
    .filter((e) => state.enabled.has(e.id))
    .reduce((a, b) => a + b.size_bytes, 0);
  const pct = state.entries.length ? (doneCount / state.entries.length) * 100 : 0;

  return (
    <div className="font-mono text-[11px]">
      <div className="px-4 py-3.5 border-b border-border">
        <div className="flex items-center justify-between">
          <span>freeing space</span>
          <b>
            {humanBytes(progressList.reduce((a, b) => a + (b.freed_bytes || 0), 0))} of{" "}
            {humanBytes(approvedTotal)}
          </b>
        </div>
        <div className="h-1.5 bg-bg-progress rounded mt-2 overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-risk-safe to-btn-primary-to rounded transition-all"
            style={{ width: `${pct}%`, boxShadow: "0 0 8px rgba(127,228,177,0.4)" }}
          />
        </div>
        <div className="text-text-muted text-[10px] mt-1.5">
          {doneCount} of {state.entries.length}
        </div>
      </div>

      {activePrompt && (
        <div className="p-4 border-b border-border bg-bg-elev-2">
          <div className="text-text mb-2">Prompt for entry {activePrompt.entry_id}</div>
          <div className="text-text-muted">{activePrompt.recipe.join(" ; ")}</div>
          <div className="mt-3 flex gap-2">
            {(["y", "n", "a", "s", "q"] as const).map((c) => (
              <button
                key={c}
                onClick={() => answerPrompt(activePrompt.entry_id, c)}
                className="px-3 py-1 rounded border border-border text-text-dim hover:text-text"
              >
                [{c}]
              </button>
            ))}
          </div>
        </div>
      )}

      {state.awaitingConfirm && (
        <div className="p-4 border-b border-border bg-bg-elev-2">
          <div className="text-text">{state.awaitingConfirm.summary}</div>
          <div className="mt-3 flex gap-2">
            <button
              onClick={confirm}
              className="bg-gradient-to-b from-btn-primary-from to-btn-primary-to text-btn-primary-fg px-4 py-1 rounded border border-btn-primary-bd"
            >
              yes, execute
            </button>
            <button onClick={cancel} className="px-4 py-1 rounded border border-border text-text-dim">
              cancel
            </button>
          </div>
        </div>
      )}

      <div className="p-4 space-y-1">
        {progressList.map((p) => (
          <div key={p.entry_id} className="grid grid-cols-[18px_1fr_90px] gap-2.5 items-center py-1.5 border-b border-border-subtle">
            <span className={`text-center ${icoColor(p.status)}`}>{ico(p.status)}</span>
            <div>
              <div className="text-text">{p.entry_id}</div>
              {p.status === "error" && p.message && (
                <div className="text-risk-danger text-[10px]">{p.message}</div>
              )}
              {p.consoleLines.slice(-1).map((c, i) => (
                <div key={i} className="text-text-muted text-[10px] truncate">{c}</div>
              ))}
            </div>
            <span className={`text-right tabular-nums ${p.status === "ok" ? "text-risk-safe" : "text-text-muted"}`}>
              {p.status === "pending" ? "—" : humanBytes(p.freed_bytes)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ico(s: string) {
  return { ok: "✓", error: "✗", skipped: "—", running: "◐", pending: "○" }[s] ?? "○";
}
function icoColor(s: string) {
  return (
    { ok: "text-risk-safe", error: "text-risk-danger", skipped: "text-text-muted", running: "text-risk-reclaim animate-pulse", pending: "text-text-muted" }[s] ?? "text-text-muted"
  );
}
