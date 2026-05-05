import { useMemo, useState } from "react";
import {
  useHistory,
  type CleanupEvent,
  type HistoryEvent,
  type MemoryActionEvent,
  type SnapshotEvent,
} from "@/hooks/useHistory";
import { DiskPageHeader } from "@/components/DiskPageHeader";
import { DomainToolTabs } from "@/components/DomainToolTabs";
import { formatAbsTime, humanBytes, timeAgo } from "@/lib/format";

type Filter = "all" | "cleanup" | "snapshot" | "memory_action";

export default function History() {
  const { data, isLoading, error } = useHistory();
  const [filter, setFilter] = useState<Filter>("all");

  const events = useMemo(() => data?.events ?? [], [data]);
  const counts = useMemo(() => {
    let cleanup = 0;
    let snapshot = 0;
    let memoryAction = 0;
    let freed = 0;
    for (const e of events) {
      if (e.type === "cleanup") {
        cleanup++;
        freed += e.total_freed_bytes || 0;
      } else if (e.type === "snapshot") {
        snapshot++;
      } else if (e.type === "memory_action") {
        memoryAction++;
      }
    }
    return { cleanup, snapshot, memoryAction, freed };
  }, [events]);

  const visible = useMemo(() => {
    if (filter === "all") return events;
    return events.filter((e) => e.type === filter);
  }, [events, filter]);

  return (
    <div className="flex flex-col h-screen font-mono text-[11px]">
      <DiskPageHeader>
        <div className="text-text-dim flex items-center gap-5">
          <span>
            <b className="text-text">{events.length}</b> events
          </span>
          <span className="text-text-muted">
            <b className="text-text-dim">{counts.cleanup}</b> cleanups ·{" "}
            <b className="text-risk-safe">{humanBytes(counts.freed)}</b> reclaimed ·{" "}
            <b className="text-text-dim">{counts.snapshot}</b> snapshots ·{" "}
            <b className="text-text-dim">{counts.memoryAction}</b> memory actions
          </span>
        </div>
      </DiskPageHeader>
      <DomainToolTabs domain="disk" />
      <header className="px-4 py-2.5 border-b border-border flex items-center gap-4">
        <div className="ml-auto flex gap-2">
          <FilterChip label="all" active={filter === "all"} onClick={() => setFilter("all")} />
          <FilterChip
            label="cleanups"
            active={filter === "cleanup"}
            onClick={() => setFilter("cleanup")}
          />
          <FilterChip
            label="snapshots"
            active={filter === "snapshot"}
            onClick={() => setFilter("snapshot")}
          />
          <FilterChip
            label="memory"
            active={filter === "memory_action"}
            onClick={() => setFilter("memory_action")}
          />
        </div>
      </header>

      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="p-8 text-text-muted animate-pulse">loading history…</div>
        )}
        {error && <div className="p-8 text-risk-danger">{String(error)}</div>}
        {!isLoading && !error && visible.length === 0 && <EmptyState filter={filter} />}
        {!isLoading && !error && visible.length > 0 && (
          <ol className="relative px-6 py-6 space-y-3">
            {visible.map((e, idx) => (
              <Event key={eventKey(e, idx)} event={e} />
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function eventKey(e: HistoryEvent, idx: number): string {
  if (e.type === "cleanup") return `cleanup:${e.job_id}:${idx}`;
  if (e.type === "memory_action") return `memory-action:${e.action_id}:${e.target_id}:${idx}`;
  return `snapshot:${e.name}:${idx}`;
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-[3px] rounded text-[10px] font-mono border transition-colors ${
        active
          ? "border-risk-reclaim bg-risk-reclaim/10 text-risk-reclaim"
          : "border-border bg-bg-elev-1 text-text-dim hover:text-text"
      }`}
    >
      {label}
    </button>
  );
}

function Event({ event }: { event: HistoryEvent }) {
  if (event.type === "cleanup") return <CleanupRow event={event} />;
  if (event.type === "memory_action") return <MemoryActionRow event={event} />;
  return <SnapshotRow event={event} />;
}

function CleanupRow({ event }: { event: CleanupEvent }) {
  const [open, setOpen] = useState(false);
  const freed = event.total_freed_bytes || 0;
  const errors = event.results.filter((r) => r.status === "error").length;
  const okCount = event.results.filter((r) => r.status === "ok").length;

  const outcomeColor =
    event.outcome === "ok"
      ? "text-risk-safe border-risk-safe"
      : event.outcome === "cancelled"
        ? "text-text-muted border-border-strong"
        : "text-risk-danger border-risk-danger";

  return (
    <li className="border border-border rounded bg-bg-elev-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left px-3 py-2.5 flex items-start gap-3 hover:bg-bg-elev-2 rounded"
      >
        <span className={`shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase tracking-widest border ${outcomeColor}`}>
          cleanup
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 justify-between">
            <span className="text-text font-medium">
              {timeAgo(event.at)}
              {event.outcome !== "ok" && (
                <span className="ml-2 text-[10px] text-text-muted uppercase">
                  · {event.outcome}
                </span>
              )}
            </span>
            <span className="tabular-nums text-risk-safe font-medium">
              {freed > 0 ? `−${humanBytes(freed)}` : humanBytes(freed)}
            </span>
          </div>
          <div className="text-text-muted text-[10px] mt-0.5 flex items-center gap-3">
            <span>{formatAbsTime(event.at)}</span>
            <span>
              {okCount} ok · {errors} errors ·{" "}
              <span className="font-mono">{event.results.length}</span> entries
            </span>
            <span className="text-text-muted ml-auto">{open ? "▲ hide" : "▼ details"}</span>
          </div>
        </div>
      </button>
      {open && (
        <div className="border-t border-border px-3 py-2 bg-bg-code">
          {event.error && (
            <div className="text-risk-danger text-[10.5px] mb-2">
              error: {event.error}
            </div>
          )}
          {event.results.length === 0 ? (
            <div className="text-text-muted">no entries cleaned</div>
          ) : (
            <table className="w-full text-[10.5px] tabular-nums">
              <thead>
                <tr className="text-text-muted uppercase text-[9px] tracking-widest">
                  <th className="text-left font-normal pb-1">entry</th>
                  <th className="text-left font-normal pb-1 w-20">status</th>
                  <th className="text-right font-normal pb-1 w-20">freed</th>
                </tr>
              </thead>
              <tbody>
                {event.results.map((r) => (
                  <tr key={r.entry_id} className="border-t border-border-subtle">
                    <td className="py-1 pr-3 text-text-dim truncate" title={r.entry_id}>
                      {r.entry_id}
                    </td>
                    <td
                      className={`py-1 pr-3 ${
                        r.status === "ok"
                          ? "text-risk-safe"
                          : r.status === "error"
                            ? "text-risk-danger"
                            : "text-text-muted"
                      }`}
                    >
                      {r.status}
                      {r.message && (
                        <span className="text-text-muted"> — {r.message}</span>
                      )}
                    </td>
                    <td className="py-1 text-right text-text-dim">
                      {humanBytes(r.freed_bytes || 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="text-text-muted text-[9px] mt-2">job {event.job_id}</div>
        </div>
      )}
    </li>
  );
}

function MemoryActionRow({ event }: { event: MemoryActionEvent }) {
  const tone =
    event.status === "ok"
      ? "text-risk-safe border-risk-safe"
      : event.status === "unsupported"
        ? "text-risk-reclaim border-risk-reclaim"
        : "text-risk-danger border-risk-danger";
  return (
    <li className="border border-border rounded bg-bg-elev-1">
      <div className="px-3 py-2.5 flex items-start gap-3">
        <span className={`shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase tracking-widest border ${tone}`}>
          memory
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 justify-between">
            <span className="text-text font-medium">
              {timeAgo(event.at)}
              <span className="ml-2 text-[10px] text-text-muted uppercase">
                · {event.status}
              </span>
            </span>
            <span className="tabular-nums text-text-dim font-medium">
              {event.estimated_bytes === null ? "unknown" : humanBytes(event.estimated_bytes)}
            </span>
          </div>
          <div className="text-text-muted text-[10px] mt-0.5 flex items-center gap-3">
            <span>{formatAbsTime(event.at)}</span>
            <span className="text-text-dim truncate">{event.label}</span>
            <span>{event.target_id}</span>
            {event.risk && <span>{event.risk}</span>}
            <span className="ml-auto text-text-muted truncate">{event.message}</span>
          </div>
        </div>
      </div>
    </li>
  );
}

function SnapshotRow({ event }: { event: SnapshotEvent }) {
  return (
    <li className="border border-border rounded bg-bg-elev-1">
      <div className="px-3 py-2.5 flex items-start gap-3">
        <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase tracking-widest border text-risk-reclaim border-risk-reclaim">
          snapshot
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 justify-between">
            <span className="text-text font-medium">{timeAgo(event.at)}</span>
            <span className="tabular-nums text-text-dim font-medium">
              {humanBytes(event.total_bytes)}
            </span>
          </div>
          <div className="text-text-muted text-[10px] mt-0.5 flex items-center gap-3">
            <span>{formatAbsTime(event.at)}</span>
            <span>
              {event.entry_count} {event.entry_count === 1 ? "entry" : "entries"}
            </span>
            {event.note && (
              <span className="text-text-dim italic truncate">“{event.note}”</span>
            )}
            <span className="ml-auto text-text-muted text-[9px]">{event.name}</span>
          </div>
        </div>
      </div>
    </li>
  );
}

function EmptyState({ filter }: { filter: Filter }) {
  const msg =
    filter === "cleanup"
      ? "No cleanups run yet."
      : filter === "snapshot"
        ? "No snapshots yet."
        : filter === "memory_action"
          ? "No memory actions run yet."
          : "No history yet. Run a scan, create a snapshot, or execute an action to populate the audit trail.";
  return (
    <div className="p-8 text-center text-text-dim">
      <div className="max-w-md mx-auto space-y-2">
        <div className="text-text text-[14px] font-medium">Empty</div>
        <div className="leading-relaxed">{msg}</div>
      </div>
    </div>
  );
}
