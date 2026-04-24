import { useEffect, useMemo, useState } from "react";
import { DiffTable } from "@/components/DiffTable";
import { useCreateSnapshot, useSnapshot, useSnapshots } from "@/hooks/useSnapshots";
import type { SnapshotMeta } from "@/hooks/useSnapshots";
import { useDiff } from "@/hooks/useDiff";
import { DiskUsageBar } from "@/components/DiskUsageBar";
import { formatAbsTime, formatMs, humanBytes, timeAgo } from "@/lib/format";

const FLASH_MS = 2000;

type SlotLabel = "A" | "B";

export default function Snapshots() {
  const { data } = useSnapshots();
  const create = useCreateSnapshot();
  const [selected, setSelected] = useState<[string | null, string | null]>([null, null]);
  const [flashName, setFlashName] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [compareToLive, setCompareToLive] = useState(false);

  const snapshots = useMemo(() => data ?? [], [data]);

  useEffect(() => {
    if (!flashName) return;
    const t = setTimeout(() => setFlashName(null), FLASH_MS);
    return () => clearTimeout(t);
  }, [flashName]);

  function slotOf(name: string): SlotLabel | null {
    if (selected[0] === name) return "A";
    if (selected[1] === name) return "B";
    return null;
  }

  function togglePick(name: string) {
    setCompareToLive(false);
    setSelected(([a, b]) => {
      if (a === name) return [null, b];
      if (b === name) return [a, null];
      if (!a) return [name, b];
      if (!b) return [a, name];
      // Both slots full → replace B (most-recent wins).
      return [a, name];
    });
  }

  function swap() {
    setSelected(([a, b]) => [b, a]);
  }

  function clear() {
    setSelected([null, null]);
    setCompareToLive(false);
  }

  function handleCreate() {
    const body = note.trim() ? { note: note.trim() } : {};
    create.mutate(body, {
      onSuccess: (d) => {
        setFlashName(d.name);
        setSelected(([, b]) => [d.name, b === d.name ? null : b]);
        setNote("");
      },
    });
  }

  // Determine chronological order for the diff: from_ = earlier, to_ = later.
  // The A/B slots are just selection identifiers — clicking order (which in a
  // newest-first list naturally puts the new snapshot in A) must not silently
  // invert the delta sign.
  const diffArgs = useMemo(() => {
    const [aName, bName] = selected;
    if (!aName) return { from: null, to: null, fromMeta: null, toMeta: null };
    const aMeta = snapshots.find((s) => s.name === aName) ?? null;
    if (compareToLive) {
      // Live is always "now", so the snapshot is always the 'before'.
      return { from: aName, to: "live", fromMeta: aMeta, toMeta: null };
    }
    if (!bName) return { from: aName, to: null, fromMeta: aMeta, toMeta: null };
    const bMeta = snapshots.find((s) => s.name === bName) ?? null;
    const at = aMeta ? new Date(aMeta.scanned_at).getTime() : 0;
    const bt = bMeta ? new Date(bMeta.scanned_at).getTime() : 0;
    if (at <= bt) return { from: aName, to: bName, fromMeta: aMeta, toMeta: bMeta };
    return { from: bName, to: aName, fromMeta: bMeta, toMeta: aMeta };
  }, [selected, snapshots, compareToLive]);
  const diff = useDiff(diffArgs.from, diffArgs.to);

  return (
    <div className="flex flex-col h-screen font-mono text-[11px]">
      <header className="px-4 py-3 border-b border-border flex items-center justify-between gap-4">
        <div className="text-text-dim">
          <b className="text-text">{snapshots.length}</b> snapshot
          {snapshots.length === 1 ? "" : "s"}
        </div>
        <DiskUsageBar />
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={create.isPending}
            placeholder="optional note…"
            className="bg-bg-elev-1 border border-border rounded px-2 py-1 text-[11px] text-text placeholder:text-text-muted w-48 focus:outline-none focus:border-risk-reclaim disabled:opacity-50"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !create.isPending) handleCreate();
            }}
          />
          <button
            onClick={handleCreate}
            disabled={create.isPending}
            className={`px-3 py-1 rounded border font-mono text-[11px] transition-colors ${
              create.isPending
                ? "border-border text-text-muted cursor-wait"
                : "border-border text-text-dim hover:text-text hover:border-risk-reclaim"
            }`}
          >
            {create.isPending ? (
              <span className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-risk-reclaim animate-pulse" />
                scanning disk…
              </span>
            ) : (
              "+ create snapshot"
            )}
          </button>
        </div>
      </header>

      {create.isError && (
        <div className="px-4 py-2 text-risk-danger text-[10.5px] border-b border-border bg-risk-danger/5">
          Failed to create snapshot: {String(create.error)}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* LEFT: slot picker + list */}
        <aside className="w-[320px] border-r border-border flex flex-col min-h-0">
          <SlotPicker
            selected={selected}
            snapshots={snapshots}
            onSwap={swap}
            onClear={clear}
          />
          <div className="flex-1 overflow-auto">
            {snapshots.map((s, idx) => {
              const prev = snapshots[idx + 1]; // older (list is newest-first)
              const delta = prev ? s.total_bytes - prev.total_bytes : null;
              const slot = slotOf(s.name);
              const flashing = flashName === s.name;
              const isAuto = s.kind === "auto";
              return (
                <button
                  key={s.name}
                  onClick={() => togglePick(s.name)}
                  className={`block w-full text-left px-3 py-2.5 border-b border-border-subtle transition-colors ${
                    flashing
                      ? "bg-bg-safe-tint text-risk-safe"
                      : slot
                        ? "bg-bg-elev-2 text-text"
                        : isAuto
                          ? "text-text-muted hover:bg-bg-elev-1"
                          : "text-text-dim hover:bg-bg-elev-1"
                  }`}
                  title={s.scanned_at}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <SlotBadge slot={slot} />
                      <span className="font-medium truncate">{timeAgo(s.scanned_at)}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {typeof s.duration_ms === "number" && (
                        <span className="text-text-muted text-[10px] tabular-nums">
                          ⏱ <span>{formatMs(s.duration_ms)}</span>
                        </span>
                      )}
                      <span className="tabular-nums text-text font-medium">
                        {humanBytes(s.total_bytes)}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-1">
                    <div className="text-text-muted text-[10px] truncate">
                      {formatAbsTime(s.scanned_at)}
                      {s.kind && (
                        <>
                          {" · "}
                          <span className="text-text-muted">{s.kind}</span>
                        </>
                      )}
                      {s.note ? (
                        <>
                          {" · "}
                          <span className="text-text-dim">{s.note}</span>
                        </>
                      ) : null}
                    </div>
                    {delta !== null && delta !== 0 ? (
                      <span
                        className={`text-[10px] tabular-nums shrink-0 ${
                          delta > 0 ? "text-risk-danger" : "text-risk-safe"
                        }`}
                      >
                        {delta > 0 ? "↑" : "↓"} {humanBytes(Math.abs(delta))}
                      </span>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* RIGHT: empty / summary / diff */}
        <section className="flex-1 overflow-auto min-w-0">
          {snapshots.length === 0 ? (
            <EmptyState />
          ) : !selected[0] && !selected[1] ? (
            <HowToUse />
          ) : selected[0] && !selected[1] && !compareToLive ? (
            <SingleSnapshotSummary
              meta={snapshots.find((x) => x.name === selected[0])!}
              onCompareToLive={() => setCompareToLive(true)}
            />
          ) : diffArgs.from && diffArgs.to ? (
            <DiffPane
              fromName={diffArgs.from}
              toName={diffArgs.to}
              fromMeta={diffArgs.fromMeta}
              toMeta={diffArgs.toMeta}
              fromSlot={selected[0] === diffArgs.from ? "A" : "B"}
              toSlot={diffArgs.to === "live" ? null : selected[0] === diffArgs.to ? "A" : "B"}
              loading={diff.isLoading}
              error={diff.error}
              data={diff.data}
            />
          ) : (
            <HowToUse />
          )}
        </section>
      </div>
    </div>
  );
}

function SlotBadge({ slot }: { slot: SlotLabel | null }) {
  if (!slot) {
    return (
      <span className="inline-block w-4 h-4 rounded border border-border shrink-0" />
    );
  }
  const colors =
    slot === "A"
      ? "bg-risk-reclaim/20 text-risk-reclaim border-risk-reclaim"
      : "bg-risk-safe/20 text-risk-safe border-risk-safe";
  return (
    <span
      className={`inline-flex items-center justify-center w-4 h-4 rounded text-[9px] font-bold border shrink-0 ${colors}`}
    >
      {slot}
    </span>
  );
}

function SlotPicker({
  selected,
  snapshots,
  onSwap,
  onClear,
}: {
  selected: [string | null, string | null];
  snapshots: SnapshotMeta[];
  onSwap: () => void;
  onClear: () => void;
}) {
  const [a, b] = selected;
  const aMeta = a ? snapshots.find((s) => s.name === a) : null;
  const bMeta = b ? snapshots.find((s) => s.name === b) : null;
  const bothFilled = !!a && !!b;
  const anyFilled = !!a || !!b;

  return (
    <div className="px-3 py-2.5 border-b border-border bg-bg-elev-1 space-y-1.5">
      <div className="text-[9.5px] uppercase tracking-widest text-text-muted">compare</div>
      <SlotRow label="A" meta={aMeta} color="text-risk-reclaim border-risk-reclaim" />
      <div className="text-text-muted text-center leading-none">↓</div>
      <SlotRow label="B" meta={bMeta} color="text-risk-safe border-risk-safe" />
      {anyFilled && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={onSwap}
            disabled={!bothFilled}
            className="px-2 py-0.5 text-[10px] rounded border border-border text-text-dim hover:text-text disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ⇅ swap
          </button>
          <button
            onClick={onClear}
            className="px-2 py-0.5 text-[10px] rounded border border-border text-text-dim hover:text-text"
          >
            clear
          </button>
        </div>
      )}
    </div>
  );
}

function SlotRow({
  label,
  meta,
  color,
}: {
  label: SlotLabel;
  meta: SnapshotMeta | null | undefined;
  color: string;
}) {
  return (
    <div className={`flex items-center gap-2 rounded border ${color} px-2 py-1`}>
      <span className="text-[9px] font-bold">{label}</span>
      <div className="flex-1 min-w-0">
        {meta ? (
          <>
            <div className="text-text text-[10.5px] truncate">{timeAgo(meta.scanned_at)}</div>
            <div className="text-text-muted text-[9.5px] truncate">{humanBytes(meta.total_bytes)}</div>
          </>
        ) : (
          <div className="text-text-muted text-[10.5px]">pick a snapshot…</div>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-3">
        <div className="text-text text-[14px] font-medium">No snapshots yet</div>
        <div className="text-text-dim leading-relaxed">
          Snapshots capture your disk usage at a point in time. Create one now and another after
          cleaning up to see exactly what reclaimed space.
        </div>
      </div>
    </div>
  );
}

function HowToUse() {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-md space-y-4">
        <div className="text-text text-[14px] font-medium">How to use snapshots</div>
        <ol className="space-y-2 text-text-dim leading-relaxed">
          <li>
            <span className="text-risk-reclaim">1.</span> Click <b>+ create snapshot</b> before a
            cleanup to save current sizes.
          </li>
          <li>
            <span className="text-risk-reclaim">2.</span> Clean caches, delete models, or just wait.
          </li>
          <li>
            <span className="text-risk-reclaim">3.</span> Pick any snapshot here to see detail, or
            pick two to diff them — you'll see exactly what changed per provider.
          </li>
        </ol>
      </div>
    </div>
  );
}

function SingleSnapshotSummary({
  meta,
  onCompareToLive,
}: {
  meta: SnapshotMeta;
  onCompareToLive: () => void;
}) {
  const full = useSnapshot(meta.name);
  const top = useMemo(() => {
    const entries = full.data?.entries ?? [];
    const byProvider = new Map<string, number>();
    for (const e of entries) {
      byProvider.set(e.provider, (byProvider.get(e.provider) ?? 0) + e.size_bytes);
    }
    return [...byProvider.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [full.data]);

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div>
        <div className="text-[9.5px] uppercase tracking-widest text-text-muted">snapshot</div>
        <h2 className="text-text text-[18px] font-medium mt-1">{timeAgo(meta.scanned_at)}</h2>
        <div className="text-text-dim text-[11px] mt-0.5">{formatAbsTime(meta.scanned_at)}</div>
      </div>

      <dl className="grid grid-cols-2 gap-x-8 gap-y-3">
        <Stat label="total reclaimable" value={humanBytes(meta.total_bytes)} big />
        <Stat label="platform" value={meta.platform} />
        <Stat label="hostname" value={meta.hostname} />
        <Stat label="note" value={meta.note ?? "—"} />
      </dl>

      <section>
        <div className="text-[9.5px] uppercase tracking-widest text-text-muted mb-2">
          top providers by size
        </div>
        {full.isLoading ? (
          <div className="text-text-muted animate-pulse">loading…</div>
        ) : top.length === 0 ? (
          <div className="text-text-muted">no entries</div>
        ) : (
          <div className="space-y-1.5">
            {top.map(([name, bytes]) => {
              const pct = meta.total_bytes > 0 ? (bytes / meta.total_bytes) * 100 : 0;
              return (
                <div key={name} className="flex items-center gap-3">
                  <div className="w-36 text-text-dim truncate">{name}</div>
                  <div className="flex-1 h-1.5 bg-bg-elev-2 rounded overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-risk-reclaim to-[#9077d6]"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="w-16 text-right tabular-nums text-text font-medium">
                    {humanBytes(bytes)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <div className="pt-2 border-t border-border">
        <button
          onClick={onCompareToLive}
          className="px-3 py-1.5 rounded border border-risk-reclaim text-risk-reclaim hover:bg-risk-reclaim/10 text-[11px]"
        >
          compare to live ↗
        </button>
        <div className="text-text-muted text-[10px] mt-1.5">
          Runs a fresh scan and diffs this snapshot against what's on disk right now.
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div>
      <dt className="text-[9.5px] uppercase tracking-widest text-text-muted">{label}</dt>
      <dd className={`text-text mt-0.5 ${big ? "text-[18px] font-medium" : "text-[12px]"}`}>
        {value}
      </dd>
    </div>
  );
}

function DiffPane({
  fromName,
  toName,
  fromMeta,
  toMeta,
  fromSlot,
  toSlot,
  loading,
  error,
  data,
}: {
  fromName: string;
  toName: string | "live";
  fromMeta: SnapshotMeta | null;
  toMeta: SnapshotMeta | null;
  fromSlot: SlotLabel | null;
  toSlot: SlotLabel | null;
  loading: boolean;
  error: unknown;
  data:
    | { rows: { provider: string; before_bytes: number; after_bytes: number; delta_bytes: number; delta_pct: number }[] }
    | undefined;
}) {
  const toLabel =
    toName === "live"
      ? "live (current disk)"
      : toMeta
        ? timeAgo(toMeta.scanned_at)
        : toName;
  const fromLabel = fromMeta ? timeAgo(fromMeta.scanned_at) : fromName;

  const totalDelta = useMemo(
    () => data?.rows.reduce((acc, r) => acc + r.delta_bytes, 0) ?? 0,
    [data],
  );

  return (
    <div className="p-6 space-y-4">
      <header className="flex items-end gap-3 flex-wrap">
        <div>
          <div className="text-[9.5px] uppercase tracking-widest text-text-muted">diff · earlier → later</div>
          <div className="flex items-center gap-3 text-[13px] mt-1">
            <RoleChip role="before" slot={fromSlot} label={fromLabel} absTime={fromMeta?.scanned_at ?? null} />
            <span className="text-text-muted">→</span>
            <RoleChip role="after" slot={toSlot} label={toLabel} absTime={toMeta?.scanned_at ?? null} />
          </div>
        </div>
        {data && (
          <div className="ml-auto text-right">
            <div className="text-[9.5px] uppercase tracking-widest text-text-muted">net change</div>
            <div
              className={`text-[14px] tabular-nums font-medium mt-0.5 ${
                totalDelta > 0
                  ? "text-risk-danger"
                  : totalDelta < 0
                    ? "text-risk-safe"
                    : "text-text"
              }`}
            >
              {totalDelta > 0 ? "+" : totalDelta < 0 ? "−" : ""}
              {humanBytes(Math.abs(totalDelta))}
            </div>
            <div className="text-text-muted text-[9px] mt-0.5">
              {totalDelta > 0 ? "disk grew" : totalDelta < 0 ? "disk shrank" : "no net change"}
            </div>
          </div>
        )}
      </header>

      {loading && <div className="text-text-muted animate-pulse">loading diff…</div>}
      {!!error && <div className="text-risk-danger">{String(error)}</div>}
      {data && <DiffTable diff={data as unknown as DiffData} />}
    </div>
  );
}

function RoleChip({
  role,
  slot,
  label,
  absTime,
}: {
  role: "before" | "after";
  slot: SlotLabel | null;
  label: string;
  absTime: string | null;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-[9px] uppercase tracking-widest text-text-muted">{role}</span>
      {slot ? <SlotBadge slot={slot} /> : null}
      <span className="text-text" title={absTime ?? undefined}>
        {label}
      </span>
    </span>
  );
}

// Mirror the DiffTable prop shape minimally.
type DiffData = Parameters<typeof DiffTable>[0]["diff"];
