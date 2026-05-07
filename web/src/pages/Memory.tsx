import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { DomainToolTabs } from "@/components/DomainToolTabs";
import {
  useExecuteMemoryAction,
  useCreateMemorySnapshot,
  useMemory,
  useMemoryHistory,
  useMemoryPlan,
  useMemoryProviders,
  useMemorySnapshotDiff,
  useMemorySnapshots,
  useMemoryWorkloads,
  type MemoryAction,
  type MemoryActionRisk,
  type MemoryConsumer,
  type MemoryConsumerKind,
  type MemoryObservationMeta,
  type MemoryPlan,
  type MemoryPlanAction,
  type MemoryPressure,
  type MemoryProvider,
  type MemoryProviderTotal,
  type MemorySnapshotDiff,
  type MemorySnapshotMeta,
  type MemorySuggestion,
  type MemorySuggestionConfidence,
  type MemoryWorkload,
} from "@/hooks/useMemory";
import { useSelectedMemoryProviders } from "@/hooks/useSelectedMemoryProviders";
import { humanBytes, timeAgo } from "@/lib/format";
import { memoryProviderIds } from "@/lib/providerFilters";

const KIND_LABEL: Record<MemoryConsumerKind, string> = {
  browser: "browsers",
  electron: "electron apps",
  docker: "docker",
  llm: "local llm",
  app: "apps",
  process: "processes",
  other: "other",
};

const KIND_ORDER: MemoryConsumerKind[] = [
  "browser",
  "electron",
  "docker",
  "llm",
  "app",
  "process",
  "other",
];
type MemoryTab = "live" | "planner" | "history" | "snapshots" | "providers";
const MEMORY_TABS = new Set<string>(["planner", "history", "snapshots", "providers"]);

const RISK_LABEL: Record<MemoryActionRisk, string> = {
  safe: "safe",
  reclaimable: "reclaim",
  dangerous: "danger",
};

const CONF_LABEL: Record<MemorySuggestionConfidence, string> = {
  high: "high confidence",
  medium: "medium confidence",
  low: "low confidence",
};

function pressureTone(pressure: MemoryPressure): { label: string; dot: string; text: string } {
  switch (pressure) {
    case "critical":
      return { label: "critical", dot: "var(--risk-danger)", text: "text-risk-danger" };
    case "warn":
      return { label: "warning", dot: "var(--risk-reclaim)", text: "text-risk-reclaim" };
    case "ok":
      return { label: "ok", dot: "var(--risk-safe)", text: "text-risk-safe" };
    case "unknown":
      return { label: "unknown", dot: "var(--text-muted)", text: "text-text-muted" };
  }
}

function pct(n: number, d: number): number {
  if (d <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((n / d) * 100)));
}

export default function Memory() {
  const { tab: rawTab } = useParams();
  const tab: MemoryTab = MEMORY_TABS.has(rawTab ?? "")
    ? (rawTab as MemoryTab)
    : "live";
  const memoryProviders = useMemoryProviders();
  const selectedProviders = useSelectedMemoryProviders();
  const selectedProviderIds = useMemo(
    () => memoryProviderIds(memoryProviders.data, selectedProviders.disabled),
    [memoryProviders.data, selectedProviders.disabled],
  );
  const { data, isLoading, isFetching, error, refetch } = useMemory(selectedProviderIds);
  const history = useMemoryHistory(tab === "history");
  const snapshots = useMemorySnapshots(tab === "snapshots");

  const grouped = useMemo(() => {
    const buckets = new Map<MemoryConsumerKind, MemoryConsumer[]>();
    for (const row of data?.consumers ?? []) {
      const existing = buckets.get(row.kind) ?? [];
      existing.push(row);
      buckets.set(row.kind, existing);
    }
    return KIND_ORDER.map((kind) => ({
      kind,
      rows: buckets.get(kind) ?? [],
    })).filter((group) => group.rows.length > 0);
  }, [data?.consumers]);

  const system = data?.system;
  const pressure = pressureTone(system?.pressure ?? "unknown");
  const usedPct = system ? pct(system.used_bytes, system.total_bytes) : 0;
  const availablePct = system ? pct(system.available_bytes, system.total_bytes) : 0;
  const providerScope = useMemo(() => {
    const rows = memoryProviders.data ?? [];
    if (!selectedProviderIds || rows.length === 0) return null;
    const selected = new Set(selectedProviderIds);
    const disabledRows = rows.filter((provider) => !selected.has(provider.id));
    return {
      enabledCount: selectedProviderIds.length,
      totalCount: rows.length,
      disabledNames: disabledRows.map((provider) => provider.name),
    };
  }, [memoryProviders.data, selectedProviderIds]);

  return (
    <div className="flex flex-col h-screen font-mono">
      <header className="px-4 py-3 border-b border-border flex items-center gap-4">
        <h1 className="text-text text-[14px] font-medium">Memory</h1>
        {data?.scanned_at && (
          <span className="text-text-dim text-[11px]" title={data.scanned_at}>
            updated {timeAgo(data.scanned_at)}
          </span>
        )}
        {providerScope && (
          <span
            className={`text-[10.5px] ${
              providerScope.disabledNames.length > 0 ? "text-risk-reclaim" : "text-text-dim"
            }`}
            title={
              providerScope.disabledNames.length > 0
                ? `Disabled: ${providerScope.disabledNames.join(", ")}`
                : undefined
            }
          >
            <span className="sm:hidden">
              {providerScope.enabledCount}/{providerScope.totalCount} providers
            </span>
            <span className="hidden sm:inline">
              {providerScope.enabledCount} of {providerScope.totalCount} providers enabled
            </span>
          </span>
        )}
        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className={`ml-auto px-2.5 py-[3px] rounded text-[10px] border transition-colors ${
            isFetching
              ? "border-border text-text-muted cursor-wait"
              : "border-border text-text-dim hover:text-text hover:border-risk-reclaim"
          }`}
        >
          {isFetching ? "refreshing..." : "refresh"}
        </button>
      </header>

      <DomainToolTabs domain="memory" />

      {tab === "live" && (
        <div className="px-4 py-3 border-b border-border bg-bg-elev-1">
          <div className="flex items-center gap-5 text-[10.5px] text-text-dim flex-wrap">
            <span className={`flex items-center gap-2 uppercase tracking-widest ${pressure.text}`}>
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ background: pressure.dot, boxShadow: `0 0 8px ${pressure.dot}` }}
              />
              {pressure.label}
            </span>
            <Metric label="used" value={system ? humanBytes(system.used_bytes) : "..."} />
            <Metric
              label="available"
              value={system ? humanBytes(system.available_bytes) : "..."}
            />
            <Metric
              label="swap"
              value={
                system?.swap_used_bytes === null || !system
                  ? "—"
                  : humanBytes(system.swap_used_bytes)
              }
            />
            <Metric
              label="compressed"
              value={
                system?.compressed_bytes === null || !system
                  ? "—"
                  : humanBytes(system.compressed_bytes)
              }
            />
            {system && (
              <span className="text-text-muted ml-auto">
                {availablePct}% available / {humanBytes(system.total_bytes)}
              </span>
            )}
          </div>
          <div className="mt-3 h-[7px] rounded-sm overflow-hidden bg-bg-control-off">
            <div
              className="h-full"
              style={{
                width: `${usedPct}%`,
                background:
                  system?.pressure === "critical"
                    ? "var(--risk-danger)"
                    : system?.pressure === "warn"
                      ? "var(--risk-reclaim)"
                      : "var(--risk-safe)",
                opacity: 0.85,
              }}
            />
          </div>
          {(data?.provider_totals.length ?? 0) > 0 && (
            <ProviderTotalsPanel
              rows={data?.provider_totals ?? []}
              totalBytes={system?.used_bytes ?? 0}
            />
          )}
        </div>
      )}

      <div className="flex-1 overflow-auto">
        {tab === "live" && error && (
          <div className="p-8 text-risk-danger text-sm">
            Error loading memory report: {String(error)}
          </div>
        )}
        {tab === "live" && isLoading && (
          <div className="p-8 text-text-muted text-sm animate-pulse">reading memory...</div>
        )}
        {tab === "live" && !isLoading && !error && data && (
          <div>
            <SuggestionsPanel suggestions={data.suggestions} />
            <div className="grid grid-cols-[minmax(220px,1fr)_120px_90px_minmax(220px,1.5fr)] gap-3 px-4 py-2 border-b border-border text-[9.5px] uppercase tracking-widest text-text-muted">
              <div>consumer</div>
              <div className="text-right">rss</div>
              <div className="text-right">pid</div>
              <div>command</div>
            </div>
            {grouped.map((group) => (
              <section key={group.kind}>
                <div className="px-4 py-2 bg-bg-elev-1 border-b border-border text-[10px] uppercase tracking-widest text-text-muted">
                  {KIND_LABEL[group.kind]} · {group.rows.length}
                </div>
                {group.rows.map((row) => (
                  <MemoryRow key={row.id} row={row} />
                ))}
              </section>
            ))}
            {grouped.length === 0 && (
              <div className="p-8 text-center text-text-dim text-sm">(no memory consumers)</div>
            )}
          </div>
        )}
        {tab === "planner" && <MemoryPlannerPanel providerIds={selectedProviderIds} />}
        {tab === "history" && (
          <MemoryHistoryPanel
            rows={history.data?.observations ?? []}
            loading={history.isLoading}
            error={history.error}
          />
        )}
        {tab === "snapshots" && (
          <MemorySnapshotsPanel
            rows={snapshots.data ?? []}
            loading={snapshots.isLoading}
            error={snapshots.error}
            providerIds={selectedProviderIds}
          />
        )}
        {tab === "providers" && (
          <MemoryProvidersPanel
            rows={memoryProviders.data ?? []}
            loading={memoryProviders.isLoading}
            error={memoryProviders.error}
            disabled={selectedProviders.disabled}
            isEnabled={selectedProviders.isEnabled}
            setEnabled={selectedProviders.setEnabled}
            setMany={selectedProviders.setMany}
          />
        )}
      </div>
    </div>
  );
}

function MemoryPlannerPanel({ providerIds }: { providerIds?: string[] }) {
  const workloads = useMemoryWorkloads();
  const plan = useMemoryPlan();
  const [selectedId, setSelectedId] = useState("llm-7b");
  const [customGiB, setCustomGiB] = useState("8");
  const [safetyGiB, setSafetyGiB] = useState("1");

  function runPlan() {
    const safety = gibToBytes(safetyGiB);
    if (selectedId === "custom") {
      const required = gibToBytes(customGiB);
      if (!required || required <= 0) return;
      plan.mutate({
        custom_label: "Custom workload",
        custom_required_bytes: required,
        safety_margin_bytes: safety,
        providers: providerIds,
      });
      return;
    }
    plan.mutate({
      workload_id: selectedId,
      safety_margin_bytes: safety,
      providers: providerIds,
    });
  }

  return (
    <div className="p-4 grid gap-4 xl:grid-cols-[360px_1fr]">
      <section className="space-y-4">
        <div className="grid gap-2">
          {(workloads.data ?? []).map((workload) => (
            <WorkloadButton
              key={workload.id}
              workload={workload}
              active={selectedId === workload.id}
              onClick={() => setSelectedId(workload.id)}
            />
          ))}
          <button
            type="button"
            onClick={() => setSelectedId("custom")}
            className={`text-left border rounded p-3 ${
              selectedId === "custom"
                ? "border-risk-reclaim bg-risk-reclaim/10"
                : "border-border bg-bg-elev-1 hover:bg-bg-elev-2"
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-text text-[12px] font-medium">Custom workload</span>
              <span className="text-text-muted text-[10px]">{customGiB || "0"} GiB</span>
            </div>
            <div className="mt-2 flex items-center gap-2 text-[10.5px] text-text-dim">
              <input
                type="number"
                min={1}
                step={0.5}
                value={customGiB}
                onChange={(e) => setCustomGiB(e.target.value)}
                className="w-20 bg-bg border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-risk-reclaim"
              />
              <span>GiB required</span>
            </div>
          </button>
        </div>
        <label className="block text-[10.5px] text-text-dim">
          <span className="block mb-1">Safety margin (GiB)</span>
          <input
            type="number"
            min={0}
            step={0.5}
            value={safetyGiB}
            onChange={(e) => setSafetyGiB(e.target.value)}
            className="w-24 bg-bg-elev-1 border border-border rounded px-2 py-1 text-text focus:outline-none focus:border-risk-reclaim"
          />
        </label>
        <button
          type="button"
          onClick={runPlan}
          disabled={plan.isPending || workloads.isLoading}
          className="px-3 py-1.5 rounded border border-risk-reclaim text-risk-reclaim hover:bg-risk-reclaim/10 disabled:opacity-50 text-[11px]"
        >
          {plan.isPending ? "checking..." : "check fit"}
        </button>
      </section>

      <section>
        {workloads.isError && (
          <div className="text-risk-danger text-sm">{String(workloads.error)}</div>
        )}
        {plan.isError && <div className="text-risk-danger text-sm">{String(plan.error)}</div>}
        {!plan.data && !plan.isPending && (
          <div className="text-text-dim text-sm p-6 border border-border rounded bg-bg-elev-1">
            Pick a workload and check fit against current memory headroom.
          </div>
        )}
        {plan.data && <PlanResult plan={plan.data} />}
      </section>
    </div>
  );
}

function ProviderTotalsPanel({
  rows,
  totalBytes,
}: {
  rows: MemoryProviderTotal[];
  totalBytes: number;
}) {
  const visible = rows.filter((row) => row.selected || row.rss_bytes > 0);
  return (
    <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      {visible.map((row) => {
        const width = totalBytes > 0 ? Math.max(2, pct(row.rss_bytes, totalBytes)) : 0;
        return (
          <div
            key={row.id}
            className={`border rounded px-2 py-2 min-w-0 ${
              row.selected
                ? "border-border bg-bg"
                : "border-border-subtle bg-bg-elev-1 opacity-60"
            }`}
          >
            <div className="flex items-center justify-between gap-2 text-[10px]">
              <span className="text-text-dim truncate">{row.name}</span>
              <span className="text-text tabular-nums shrink-0">
                {humanBytes(row.rss_bytes)}
              </span>
            </div>
            <div className="mt-1 h-[4px] bg-bg-control-off rounded-sm overflow-hidden">
              <div
                className="h-full bg-risk-reclaim/80"
                style={{ width: `${width}%` }}
              />
            </div>
            <div className="mt-1 text-[9.5px] text-text-muted">
              {row.consumer_count} process{row.consumer_count === 1 ? "" : "es"}
              {!row.selected && " · disabled"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function WorkloadButton({
  workload,
  active,
  onClick,
}: {
  workload: MemoryWorkload;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left border rounded p-3 ${
        active
          ? "border-risk-reclaim bg-risk-reclaim/10"
          : "border-border bg-bg-elev-1 hover:bg-bg-elev-2"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-text text-[12px] font-medium">{workload.label}</span>
        <span className="text-text-muted text-[10px]">
          {humanBytes(workload.required_bytes)}
        </span>
      </div>
      <p className="text-text-dim text-[10.5px] leading-relaxed mt-1">
        {workload.description}
      </p>
    </button>
  );
}

function PlanResult({ plan }: { plan: MemoryPlan }) {
  const tone = plan.fits_now
    ? "border-risk-safe text-risk-safe"
    : plan.remaining_deficit_bytes === 0
      ? "border-risk-reclaim text-risk-reclaim"
      : "border-risk-danger text-risk-danger";
  return (
    <div className="border border-border rounded bg-bg-elev-1">
      <div className="p-4 border-b border-border">
        <div className={`inline-flex px-2 py-[3px] rounded border text-[10px] ${tone}`}>
          {plan.fits_now
            ? "fits now"
            : plan.remaining_deficit_bytes === 0
              ? "fits after plan"
              : "does not fit"}
        </div>
        <h2 className="text-text text-[16px] font-medium mt-3">{plan.workload.label}</h2>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 p-4 text-[11px]">
        <PlanMetric label="required" value={humanBytes(plan.required_bytes)} />
        <PlanMetric label="available" value={humanBytes(plan.available_bytes)} />
        <PlanMetric label="usable" value={humanBytes(plan.usable_bytes)} />
        <PlanMetric label="os reserve" value={humanBytes(plan.os_reserve_bytes)} />
        <PlanMetric label="safety margin" value={humanBytes(plan.safety_margin_bytes)} />
        <PlanMetric
          label="deficit"
          value={plan.deficit_bytes === 0 ? "0 B" : humanBytes(plan.deficit_bytes)}
        />
      </div>
      {!plan.fits_now && (
        <div className="p-4 border-t border-border">
          <div className="flex items-center justify-between gap-3 mb-2">
            <h3 className="text-text text-[12px] font-medium">Free-up plan</h3>
            <span className="text-text-muted text-[10px]">
              {humanBytes(plan.planned_reclaim_bytes)} planned
            </span>
          </div>
          {plan.actions.length === 0 ? (
            <div className="text-text-dim text-[11px]">No candidate actions yet.</div>
          ) : (
            <div className="space-y-1.5">
              {plan.actions.map((action) => (
                <PlanActionRow key={`${action.suggestion_id}:${action.action_id}`} action={action} />
              ))}
            </div>
          )}
          {plan.remaining_deficit_bytes > 0 && (
            <div className="text-risk-danger text-[11px] mt-3">
              Still short by {humanBytes(plan.remaining_deficit_bytes)}.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PlanMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9.5px] uppercase tracking-widest text-text-muted">{label}</div>
      <div className="text-text tabular-nums mt-0.5">{value}</div>
    </div>
  );
}

function PlanActionRow({ action }: { action: MemoryPlanAction }) {
  const cls =
    action.risk === "dangerous"
      ? "text-risk-danger"
      : action.risk === "reclaimable"
        ? "text-risk-reclaim"
        : "text-risk-safe";
  return (
    <div className="grid grid-cols-[1fr_110px_90px] gap-3 items-center text-[11px] border-b border-border-subtle py-1.5">
      <div className="text-text truncate">{action.label}</div>
      <div className="text-right tabular-nums text-text-dim">
        {action.estimated_bytes === null ? "unknown" : humanBytes(action.estimated_bytes)}
      </div>
      <div className={`text-right ${cls}`}>{action.risk}</div>
    </div>
  );
}

function gibToBytes(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return Math.round(parsed * 1024 ** 3);
}

function MemoryHistoryPanel({
  rows,
  loading,
  error,
}: {
  rows: MemoryObservationMeta[];
  loading: boolean;
  error: unknown;
}) {
  if (error) {
    return <div className="p-8 text-risk-danger text-sm">{String(error)}</div>;
  }
  if (loading) {
    return <div className="p-8 text-text-muted text-sm animate-pulse">loading memory history...</div>;
  }
  if (rows.length === 0) {
    return <div className="p-8 text-text-dim text-sm">No memory observations recorded yet.</div>;
  }
  return (
    <div>
      <div className="grid grid-cols-[160px_95px_1fr_120px_120px_80px] gap-3 px-4 py-2 border-b border-border text-[9.5px] uppercase tracking-widest text-text-muted">
        <div>time</div>
        <div>pressure</div>
        <div>top consumer</div>
        <div className="text-right">available</div>
        <div className="text-right">swap</div>
        <div className="text-right">ideas</div>
      </div>
      {rows.map((row) => (
        <div
          key={row.id}
          className="grid grid-cols-[160px_95px_1fr_120px_120px_80px] gap-3 px-4 py-2 border-b border-border-subtle text-[11px] items-center hover:bg-bg-elev-1"
        >
          <div className="text-text-dim" title={row.scanned_at}>
            {timeAgo(row.scanned_at)}
          </div>
          <div className={pressureTone(row.pressure).text}>{row.pressure}</div>
          <div className="min-w-0">
            <span className="text-text truncate">{row.top_consumer_name ?? "—"}</span>
            {row.top_consumer_rss_bytes !== null && (
              <span className="text-text-muted"> · {humanBytes(row.top_consumer_rss_bytes)}</span>
            )}
          </div>
          <div className="text-right tabular-nums">{humanBytes(row.available_bytes)}</div>
          <div className="text-right tabular-nums">
            {row.swap_used_bytes === null ? "—" : humanBytes(row.swap_used_bytes)}
          </div>
          <div className="text-right tabular-nums">{row.suggestion_count}</div>
        </div>
      ))}
    </div>
  );
}

function MemorySnapshotsPanel({
  rows,
  loading,
  error,
  providerIds,
}: {
  rows: MemorySnapshotMeta[];
  loading: boolean;
  error: unknown;
  providerIds?: string[];
}) {
  const create = useCreateMemorySnapshot();
  const [note, setNote] = useState("");
  const [selected, setSelected] = useState<[string | null, string | null]>([null, null]);
  const diff = useMemorySnapshotDiff(selected[0], selected[1], !!selected[0] && !!selected[1]);

  function toggle(name: string) {
    setSelected(([a, b]) => {
      if (a === name) return [null, b];
      if (b === name) return [a, null];
      if (!a) return [name, b];
      return [a, name];
    });
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="optional note..."
          className="bg-bg-elev-1 border border-border rounded px-2 py-1 text-[11px] text-text placeholder:text-text-muted w-56 focus:outline-none focus:border-risk-reclaim"
        />
        <button
          type="button"
          onClick={() =>
            create.mutate(
              { note: note.trim() || null, providerIds },
              { onSuccess: () => setNote("") },
            )
          }
          disabled={create.isPending}
          className="px-3 py-1 rounded border border-border text-[11px] text-text-dim hover:text-text disabled:opacity-50"
        >
          {create.isPending ? "capturing..." : "+ memory snapshot"}
        </button>
        <span className="text-text-muted text-[10px] ml-auto">{rows.length} snapshots</span>
      </div>
      {error ? <div className="text-risk-danger text-sm">{String(error)}</div> : null}
      {loading && <div className="text-text-muted text-sm animate-pulse">loading snapshots...</div>}
      {!loading && rows.length === 0 && (
        <div className="text-text-dim text-sm">No memory snapshots yet.</div>
      )}
      {rows.length > 0 && (
        <div className="grid grid-cols-[24px_160px_90px_1fr_120px_120px] gap-3 border-t border-border text-[11px]">
          {rows.map((row) => {
            const picked = selected[0] === row.name || selected[1] === row.name;
            return (
              <button
                key={row.name}
                type="button"
                onClick={() => toggle(row.name)}
                className={`contents text-left ${picked ? "text-risk-reclaim" : "text-text-dim"}`}
              >
                <span className="px-2 py-2 border-b border-border-subtle">{picked ? "●" : "○"}</span>
                <span className="py-2 border-b border-border-subtle" title={row.created_at}>
                  {timeAgo(row.created_at)}
                </span>
                <span className={`py-2 border-b border-border-subtle ${pressureTone(row.pressure).text}`}>
                  {row.pressure}
                </span>
                <span className="py-2 border-b border-border-subtle text-text truncate">
                  {row.note || row.top_consumer_name || row.name}
                </span>
                <span className="py-2 border-b border-border-subtle text-right tabular-nums">
                  {humanBytes(row.available_bytes)}
                </span>
                <span className="py-2 border-b border-border-subtle text-right tabular-nums">
                  {row.top_consumer_rss_bytes === null ? "—" : humanBytes(row.top_consumer_rss_bytes)}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {selected[0] && selected[1] && (
        <MemoryDiffPanel diff={diff.data} loading={diff.isLoading} error={diff.error} />
      )}
    </div>
  );
}

function MemoryDiffPanel({
  diff,
  loading,
  error,
}: {
  diff: MemorySnapshotDiff | undefined;
  loading: boolean;
  error: unknown;
}) {
  if (loading) return <div className="text-text-muted text-sm animate-pulse">loading diff...</div>;
  if (error) return <div className="text-risk-danger text-sm">{String(error)}</div>;
  if (!diff) return null;
  return (
    <section className="border-t border-border pt-4">
      <div className="grid grid-cols-4 gap-3 text-[11px]">
        <DiffMetric label="available" bytes={diff.available_delta_bytes} />
        <DiffMetric label="used" bytes={diff.used_delta_bytes} />
        <DiffMetric label="swap" bytes={diff.swap_delta_bytes} />
        <DiffMetric label="compressed" bytes={diff.compressed_delta_bytes} />
      </div>
      {diff.top_consumer_deltas.length > 0 && (
        <div className="mt-4">
          <div className="text-[9.5px] uppercase tracking-widest text-text-muted mb-2">
            top consumer deltas
          </div>
          {diff.top_consumer_deltas.map((row) => (
            <div
              key={row.id}
              className="grid grid-cols-[1fr_120px] gap-3 py-1.5 border-b border-border-subtle text-[11px]"
            >
              <span className="text-text truncate">{row.name}</span>
              <span className={`text-right tabular-nums ${row.delta_rss_bytes > 0 ? "text-risk-danger" : "text-risk-safe"}`}>
                {row.delta_rss_bytes > 0 ? "+" : "−"}
                {humanBytes(Math.abs(row.delta_rss_bytes))}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function DiffMetric({ label, bytes }: { label: string; bytes: number | null }) {
  const cls = bytes === null ? "text-text-muted" : bytes > 0 ? "text-risk-danger" : bytes < 0 ? "text-risk-safe" : "text-text";
  return (
    <div>
      <div className="text-[9.5px] uppercase tracking-widest text-text-muted">{label}</div>
      <div className={`tabular-nums ${cls}`}>
        {bytes === null ? "—" : `${bytes > 0 ? "+" : bytes < 0 ? "−" : ""}${humanBytes(Math.abs(bytes))}`}
      </div>
    </div>
  );
}

function MemoryProvidersPanel({
  rows,
  loading,
  error,
  disabled,
  isEnabled,
  setEnabled,
  setMany,
}: {
  rows: MemoryProvider[];
  loading: boolean;
  error: unknown;
  disabled: Set<string>;
  isEnabled: (id: string) => boolean;
  setEnabled: (id: string, enabled: boolean) => void;
  setMany: (ids: string[], enabled: boolean) => void;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (provider) =>
        provider.name.toLowerCase().includes(q) ||
        provider.kind.toLowerCase().includes(q) ||
        provider.description.toLowerCase().includes(q) ||
        (provider.detail ?? "").toLowerCase().includes(q),
    );
  }, [query, rows]);

  if (error) return <div className="p-8 text-risk-danger text-sm">{String(error)}</div>;
  if (loading) return <div className="p-8 text-text-muted text-sm animate-pulse">loading providers...</div>;
  const enabledCount = rows.filter((provider) => !disabled.has(provider.id)).length;
  const allEnabled = rows.length > 0 && enabledCount === rows.length;
  const noneEnabled = enabledCount === 0;
  const mixed = !allEnabled && !noneEnabled;

  function toggleAll() {
    setMany(rows.map((provider) => provider.id), noneEnabled);
  }

  return (
    <>
      <header className="px-4 py-2.5 border-b border-border flex items-center gap-4 flex-wrap">
        <label className="relative block w-full max-w-[360px] flex-1 min-w-[260px]">
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search memory providers by name or scope..."
            className="w-full bg-bg-elev-1 border border-border rounded pl-7 pr-8 py-1.5 text-[11px] text-text placeholder:text-text-muted focus:outline-none focus:border-risk-reclaim"
          />
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none">
            ⌕
          </span>
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text"
            >
              ✕
            </button>
          )}
        </label>
        <div className="ml-auto flex items-center gap-4 text-[11px] text-text-dim">
          {query && (
            <span className="text-text-muted">
              {filtered.length} match{filtered.length === 1 ? "" : "es"}
            </span>
          )}
          <span>
            <b className="text-text">{enabledCount}</b> of{" "}
            <b className="text-text">{rows.length}</b> providers enabled
          </span>
          <div className="flex items-center gap-2">
            <span className="text-text-muted text-[10px]">{noneEnabled ? "enable all" : "disable all"}</span>
            <button
              type="button"
              onClick={toggleAll}
              disabled={rows.length === 0}
              aria-pressed={!noneEnabled}
              aria-label={noneEnabled ? "Enable all memory providers" : "Disable all memory providers"}
              className={`w-[36px] h-[18px] rounded-full relative transition-colors ${
                allEnabled
                  ? "bg-btn-primary-to"
                  : mixed
                    ? "bg-btn-primary-to/50"
                    : "bg-bg-control-off"
              }`}
            >
              <span
                className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all ${
                  noneEnabled ? "left-[2px] bg-text-muted" : "right-[2px]"
                }`}
              />
            </button>
          </div>
        </div>
      </header>
      <div className="px-4 py-2 border-b border-border text-text-muted text-[10px]">
        Toggle off to exclude a memory provider from live reports, plans, snapshots, and history.
        Preference is stored locally.
      </div>
      <div className="px-4">
        <div className="grid grid-cols-[48px_minmax(120px,1fr)_92px] lg:grid-cols-[60px_minmax(160px,1fr)_120px_minmax(220px,2fr)] gap-3 px-3 py-2 border-b border-border text-[9.5px] uppercase tracking-widest text-text-muted">
          <div>enabled</div>
          <div>provider</div>
          <div>status</div>
          <div className="hidden lg:block">scope</div>
        </div>
        {filtered.map((provider) => {
          const enabled = isEnabled(provider.id);
          return (
            <div
              key={provider.id}
              className="grid grid-cols-[48px_minmax(120px,1fr)_92px] lg:grid-cols-[60px_minmax(160px,1fr)_120px_minmax(220px,2fr)] gap-3 px-3 py-2.5 items-center border-b border-border-subtle hover:bg-bg-elev-1 text-[11px]"
            >
              <button
                type="button"
                onClick={() => setEnabled(provider.id, !enabled)}
                aria-pressed={enabled}
                aria-label={`Toggle ${provider.name}`}
                className={`w-[30px] h-[16px] rounded-full relative transition-colors ${
                  enabled ? "bg-btn-primary-to" : "bg-bg-control-off"
                }`}
              >
                <span
                  className={`absolute top-[2px] w-[12px] h-[12px] rounded-full bg-white transition-all ${
                    enabled ? "right-[2px]" : "left-[2px] bg-text-muted"
                  }`}
                />
              </button>
              <div className="min-w-0">
                <div className={`font-medium truncate ${enabled ? "text-text" : "text-text-muted"}`}>
                  {provider.name}
                </div>
                <div className="text-text-muted text-[9.5px] mt-px">{provider.kind}</div>
                <div className="lg:hidden text-text-dim text-[10px] mt-1 leading-relaxed">
                  {provider.description}
                </div>
              </div>
              <span
                className={`text-[9.5px] uppercase tracking-widest ${
                  provider.status === "available"
                    ? "text-risk-safe"
                    : provider.status === "planned"
                      ? "text-text-muted"
                      : "text-risk-danger"
                }`}
              >
                {provider.status}
              </span>
              <div className="hidden lg:block min-w-0">
                <div className="text-text-dim leading-relaxed">{provider.description}</div>
                {provider.detail && (
                  <div className="text-text-muted text-[9.5px] mt-1 truncate" title={provider.detail}>
                    {provider.detail}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div className="p-8 text-center text-text-dim text-sm">
            {query ? (
              <>
                No memory providers match <span className="text-text">&ldquo;{query}&rdquo;</span>.
              </>
            ) : (
              "No memory providers."
            )}
          </div>
        )}
      </div>
    </>
  );
}

function SuggestionsPanel({ suggestions }: { suggestions: MemorySuggestion[] }) {
  const execute = useExecuteMemoryAction();
  const [pending, setPending] = useState<{
    suggestion: MemorySuggestion;
    action: MemoryAction;
  } | null>(null);
  if (suggestions.length === 0) {
    return (
      <div className="px-4 py-3 border-b border-border text-[11px] text-text-dim">
        No memory suggestions right now.
      </div>
    );
  }
  return (
    <section className="px-4 py-3 border-b border-border bg-bg">
      <div className="flex items-center justify-between gap-4 mb-2">
        <h2 className="text-text text-[12px] font-medium">Suggestions</h2>
        <span className="text-text-muted text-[10px]">{suggestions.length} advisory</span>
      </div>
      {pending && (
        <div className="mb-2 border border-risk-reclaim bg-risk-reclaim/5 rounded px-3 py-2 text-[11px] flex items-center gap-3">
          <div className="min-w-0">
            <div className="text-text">Confirm: {pending.action.label}</div>
            <div className="text-text-muted truncate">
              {pending.suggestion.title} · {pending.action.risk}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setPending(null)}
            className="ml-auto px-2 py-1 rounded border border-border text-text-dim hover:text-text"
          >
            cancel
          </button>
          <button
            type="button"
            disabled={execute.isPending}
            onClick={() =>
              execute.mutate(
                {
                  id: pending.action.id,
                  kind: pending.action.kind,
                  target_id: pending.action.target_id,
                  label: pending.action.label,
                  estimated_bytes: pending.action.estimated_bytes,
                  risk: pending.action.risk,
                  confirmed: true,
                },
                { onSuccess: () => setPending(null) },
              )
            }
            className="px-2 py-1 rounded border border-risk-reclaim text-risk-reclaim hover:bg-risk-reclaim/10 disabled:opacity-50"
          >
            {execute.isPending ? "running..." : "confirm"}
          </button>
        </div>
      )}
      {execute.data && (
        <div
          className={`mb-2 border rounded px-3 py-2 text-[11px] ${
            execute.data.status === "ok"
              ? "border-risk-safe text-risk-safe"
              : "border-risk-danger text-risk-danger"
          }`}
        >
          {execute.data.message}
        </div>
      )}
      {execute.isError && (
        <div className="mb-2 border border-risk-danger rounded px-3 py-2 text-[11px] text-risk-danger">
          {String(execute.error)}
        </div>
      )}
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {suggestions.map((suggestion) => (
          <SuggestionCard
            key={suggestion.id}
            suggestion={suggestion}
            onAction={(action) => setPending({ suggestion, action })}
          />
        ))}
      </div>
    </section>
  );
}

function SuggestionCard({
  suggestion,
  onAction,
}: {
  suggestion: MemorySuggestion;
  onAction: (action: MemoryAction) => void;
}) {
  const risk = highestRisk(suggestion);
  return (
    <article className="border border-border bg-bg-elev-1 rounded p-3 min-w-0">
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-text text-[11.5px] font-medium leading-snug">
          {suggestion.title}
        </h3>
        {suggestion.estimated_bytes !== null && (
          <span className="text-text tabular-nums text-[10.5px] shrink-0">
            ~{humanBytes(suggestion.estimated_bytes)}
          </span>
        )}
      </div>
      <p className="text-text-dim text-[10.5px] leading-relaxed mb-3">
        {suggestion.reason}
      </p>
      <div className="flex flex-wrap gap-1.5">
        <Pill tone={risk}>{RISK_LABEL[risk]}</Pill>
        <Pill>{CONF_LABEL[suggestion.confidence]}</Pill>
        {suggestion.actions.map((action) => (
          <ActionPill key={action.id} action={action} onClick={() => onAction(action)} />
        ))}
      </div>
    </article>
  );
}

function isExecutableAction(action: MemoryAction): boolean {
  return ["stop_container", "stop_service", "quit_app", "terminate_process"].includes(
    action.kind,
  );
}

function ActionPill({
  action,
  onClick,
}: {
  action: MemoryAction;
  onClick: () => void;
}) {
  if (!isExecutableAction(action)) {
    return <Pill>{action.label}</Pill>;
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-1.5 py-[2px] rounded border text-[9.5px] border-border text-text-muted hover:text-text hover:border-risk-reclaim"
    >
      {action.label}
    </button>
  );
}

function highestRisk(suggestion: MemorySuggestion): MemoryActionRisk {
  const risks = suggestion.actions.map((a) => a.risk);
  if (risks.includes("dangerous")) return "dangerous";
  if (risks.includes("reclaimable")) return "reclaimable";
  return "safe";
}

function Pill({
  tone,
  children,
}: {
  tone?: MemoryActionRisk;
  children: React.ReactNode;
}) {
  const cls =
    tone === "dangerous"
      ? "border-risk-danger text-risk-danger"
      : tone === "reclaimable"
        ? "border-risk-reclaim text-risk-reclaim"
        : tone === "safe"
          ? "border-risk-safe text-risk-safe"
          : "border-border text-text-muted";
  return (
    <span className={`px-1.5 py-[2px] rounded border text-[9.5px] ${cls}`}>
      {children}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <b className="text-text tabular-nums">{value}</b>{" "}
      <span className="text-text-muted">{label}</span>
    </span>
  );
}

function MemoryRow({ row }: { row: MemoryConsumer }) {
  return (
    <div className="grid grid-cols-[minmax(220px,1fr)_120px_90px_minmax(220px,1.5fr)] gap-3 px-4 py-[7px] items-center border-b border-border-subtle hover:bg-bg-elev-1 text-[11px]">
      <div className="min-w-0">
        <div className="text-text font-medium truncate">{row.name}</div>
        <div className="text-text-muted text-[9.5px] mt-px">{KIND_LABEL[row.kind]}</div>
      </div>
      <div className="text-right tabular-nums font-medium">{humanBytes(row.rss_bytes)}</div>
      <div className="text-right text-text-dim tabular-nums">{row.pid ?? "—"}</div>
      <div className="text-text-muted text-[10px] truncate" title={row.command ?? undefined}>
        {row.command ?? ""}
      </div>
    </div>
  );
}
