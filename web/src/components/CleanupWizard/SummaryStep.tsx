import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";
import { NavIcon } from "@/components/NavIcon";
import { useWizardContext } from "./CleanupWizardState";
import { humanBytes } from "@/lib/format";

export function SummaryStep() {
  const { state, close } = useWizardContext();
  const results = state.results ?? [];
  const reclaimed =
    state.estimatedReclaimedBytes ??
    results.reduce((a, b) => a + (b.freed_bytes || 0), 0);
  const errors = results.filter((r) => r.status === "error");
  // What the disk actually released, as opposed to what was deleted.
  const freeDelta =
    state.freeBeforeBytes !== null && state.freeAfterBytes !== null
      ? state.freeAfterBytes - state.freeBeforeBytes
      : null;

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
          {state.bytesVerified ? "Verified reclaimed" : "Estimated reclaimed"}{" "}
          <b className="text-risk-safe">
            {state.bytesVerified ? "" : "~"}{humanBytes(reclaimed)}
          </b>.{" "}
          {errors.length} error{errors.length === 1 ? "" : "s"}.
        </div>
        {freeDelta !== null && (
          <div className="text-text-dim mt-1">
            Free space {humanBytes(state.freeBeforeBytes ?? 0)} →{" "}
            {humanBytes(state.freeAfterBytes ?? 0)} (
            <span className={freeDelta >= 0 ? "text-risk-safe" : "text-risk-danger"}>
              {freeDelta >= 0 ? "+" : "-"}
              {humanBytes(Math.abs(freeDelta))}
            </span>
            ).
          </div>
        )}
      </div>
      {state.freeSpaceLagged && (
        <div
          role="alert"
          className="border border-risk-reclaim rounded p-3 text-text-dim leading-relaxed"
        >
          <span className="inline-flex items-start gap-1.5">
            <span className="shrink-0 mt-[2px]">
              <NavIcon icon={AlertTriangle} size={12} />
            </span>
            <span>
              The disk released far less than was deleted. On macOS, Time Machine local
              snapshots keep a deleted file&apos;s blocks until they are thinned. The{" "}
              <Link
                to="/disk?provider=time-machine-local-snapshots"
                onClick={close}
                className="underline text-text"
              >
                Time Machine snapshots
              </Link>{" "}
              view lists them, with a command to thin each one.
            </span>
          </span>
        </div>
      )}
      <div className="border border-border rounded">
        {results.map((r) => (
          <div key={r.entry_id} className="grid grid-cols-[1fr_100px_80px] gap-3 px-3 py-2 border-b border-border-subtle last:border-b-0">
            <div>
              <div className="text-text">{r.entry_id}</div>
              {r.status === "error" && r.message && (
                <div className="text-risk-danger text-[10px] mt-0.5 whitespace-pre-line">{r.message}</div>
              )}
            </div>
            <div className={r.status === "ok" ? "text-risk-safe" : r.status === "error" ? "text-risk-danger" : "text-text-muted"}>
              {r.status}
            </div>
            <div className="text-right tabular-nums">
              {r.bytes_verified ? "" : "~"}
              {humanBytes(r.freed_bytes)}
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2 justify-end">
        <button onClick={close} className="bg-gradient-to-b from-btn-primary-from to-btn-primary-to text-btn-primary-fg px-4 py-1.5 rounded border border-btn-primary-bd">
          done
        </button>
      </div>
    </div>
  );
}
