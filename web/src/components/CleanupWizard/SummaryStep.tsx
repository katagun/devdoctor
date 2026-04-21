import { useWizardContext } from "./CleanupWizardState";
import { humanBytes } from "@/lib/format";

export function SummaryStep() {
  const { state, close } = useWizardContext();
  const results = state.results ?? [];
  const freed = results.reduce((a, b) => a + (b.freed_bytes || 0), 0);
  const errors = results.filter((r) => r.status === "error");

  return (
    <div className="p-6 font-mono text-[11px] space-y-4">
      {state.error && (
        <div className="border border-risk-danger bg-risk-danger/10 rounded p-3 text-risk-danger">
          <div className="font-medium">Cleanup failed</div>
          <div className="text-[10px] mt-1">{state.error}</div>
        </div>
      )}
      <div>
        <div className="text-[14px] text-text">
          {state.error ? "Cleanup stopped." : "Cleanup complete."}
        </div>
        <div className="text-text-dim mt-1">
          Freed <b className="text-risk-safe">{humanBytes(freed)}</b>. {errors.length} error{errors.length === 1 ? "" : "s"}.
        </div>
      </div>
      <div className="border border-border rounded">
        {results.map((r) => (
          <div key={r.entry_id} className="grid grid-cols-[1fr_100px_80px] gap-3 px-3 py-2 border-b border-border-subtle last:border-b-0">
            <div>
              <div className="text-text">{r.entry_id}</div>
              {r.status === "error" && r.message && (
                <div className="text-risk-danger text-[10px] mt-0.5">{r.message}</div>
              )}
            </div>
            <div className={r.status === "ok" ? "text-risk-safe" : r.status === "error" ? "text-risk-danger" : "text-text-muted"}>
              {r.status}
            </div>
            <div className="text-right tabular-nums">{humanBytes(r.freed_bytes)}</div>
          </div>
        ))}
      </div>
      <div className="flex gap-2 justify-end">
        <button onClick={close} className="bg-gradient-to-b from-[#3aa670] to-[#2a7f55] text-[#e8fff3] px-4 py-1.5 rounded border border-[#3aa670]">
          done
        </button>
      </div>
    </div>
  );
}
