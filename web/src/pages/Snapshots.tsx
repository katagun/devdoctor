import { useEffect, useMemo, useState } from "react";
import { DiffTable } from "@/components/DiffTable";
import { useCreateSnapshot, useSnapshots } from "@/hooks/useSnapshots";
import { useDiff } from "@/hooks/useDiff";

const FLASH_MS = 2000;

export default function Snapshots() {
  const { data } = useSnapshots();
  const create = useCreateSnapshot();
  const [selected, setSelected] = useState<[string | null, string | null]>([null, null]);
  const [flashName, setFlashName] = useState<string | null>(null);

  const snapshots = data ?? [];
  const pickable = useMemo(
    () => snapshots.map((s) => ({ name: s.name, label: `${s.scanned_at} — ${s.note ?? "(no note)"}` })),
    [snapshots],
  );
  const diff = useDiff(selected[0], selected[1]);

  // Clear the "just created" flash after a short period.
  useEffect(() => {
    if (!flashName) return;
    const t = setTimeout(() => setFlashName(null), FLASH_MS);
    return () => clearTimeout(t);
  }, [flashName]);

  function togglePick(name: string) {
    setSelected(([a, b]) => {
      if (a === name) return [null, b];
      if (b === name) return [a, null];
      if (!a) return [name, b];
      if (!b) return [a, name];
      return [b, name];
    });
  }

  function handleCreate() {
    create.mutate(
      {},
      {
        onSuccess: (d) => {
          setFlashName(d.name);
          // Auto-select the new snapshot in slot A so the user sees it appear.
          setSelected(([, b]) => [d.name, b === d.name ? null : b]);
        },
      },
    );
  }

  return (
    <div className="flex flex-col h-screen font-mono text-[11px]">
      <div className="flex justify-between px-4 py-3 border-b border-border">
        <div className="text-text-dim">{snapshots.length} snapshots</div>
        <div className="flex flex-col items-end gap-1">
          <button
            onClick={handleCreate}
            disabled={create.isPending}
            className={`px-3 py-1 rounded border font-mono text-[11px] transition-colors ${
              create.isPending
                ? "border-border text-text-muted cursor-wait"
                : "border-border text-text-dim hover:text-text"
            }`}
          >
            {create.isPending ? (
              <span className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-risk-reclaim animate-pulse" />
                scanning disk… (this can take a moment)
              </span>
            ) : (
              "+ create snapshot"
            )}
          </button>
          {create.isError && (
            <div className="text-risk-danger text-[10px]">{String(create.error)}</div>
          )}
        </div>
      </div>
      <div className="flex-1 flex">
        <div className="w-[280px] border-r border-border overflow-auto">
          {pickable.map((s) => {
            const picked = selected[0] === s.name || selected[1] === s.name;
            const flashing = flashName === s.name;
            return (
              <button
                key={s.name}
                onClick={() => togglePick(s.name)}
                className={`block w-full text-left px-3 py-2 border-b border-[#10151b] text-[10.5px] transition-colors ${
                  flashing
                    ? "bg-[#13241a] text-risk-safe"
                    : picked
                      ? "bg-bg-elev-2 text-text"
                      : "text-text-dim hover:bg-bg-elev-1"
                }`}
              >
                <div className="font-medium">{s.name}</div>
                <div className="text-text-muted text-[10px] mt-0.5">{s.label}</div>
              </button>
            );
          })}
        </div>
        <div className="flex-1 overflow-auto">
          {!selected[0] || !selected[1] ? (
            <div className="p-8 text-text-muted">Select two snapshots to compare.</div>
          ) : diff.isLoading ? (
            <div className="p-8 text-text-muted animate-pulse">loading diff…</div>
          ) : diff.error ? (
            <div className="p-8 text-risk-danger">{String(diff.error)}</div>
          ) : diff.data ? (
            <DiffTable diff={diff.data} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
