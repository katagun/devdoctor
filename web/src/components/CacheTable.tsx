import { useMemo, useState } from "react";
import { Checkbox } from "./Checkbox";
import { RiskBadge } from "./RiskBadge";
import { humanBytes, staleness, RiskValue } from "@/lib/format";
import { ProviderIcon } from "./ProviderIcon";

export interface CacheTableRow {
  id: string;
  provider: string;
  label: string;
  path: string;
  size_bytes: number;
  risk: RiskValue;
  mtime: number | null;
  recipeHint: string;
}

type SortKey = "provider" | "size" | "risk" | "stale";
type SortDir = "asc" | "desc";

// Rank risk so "desc" shows DANGER at top.
const RISK_RANK: Record<RiskValue, number> = {
  safe: 0,
  reclaimable: 1,
  dangerous: 2,
};

// Click a fresh column → jump to the "interesting" end.
const DEFAULT_DIR: Record<SortKey, SortDir> = {
  provider: "asc",
  size: "desc",
  risk: "desc",
  stale: "desc",
};

function makeComparator(
  key: SortKey,
  dir: SortDir,
  now: number,
): (a: CacheTableRow, b: CacheTableRow) => number {
  const sign = dir === "asc" ? 1 : -1;
  return (a, b) => {
    switch (key) {
      case "size":
        return sign * (a.size_bytes - b.size_bytes);
      case "provider":
        return (
          sign * (a.provider.localeCompare(b.provider) || a.label.localeCompare(b.label))
        );
      case "risk":
        return (
          sign * (RISK_RANK[a.risk] - RISK_RANK[b.risk]) ||
          b.size_bytes - a.size_bytes
        );
      case "stale": {
        if (a.mtime === null && b.mtime === null) return 0;
        if (a.mtime === null) return 1;
        if (b.mtime === null) return -1;
        const ageA = now - a.mtime;
        const ageB = now - b.mtime;
        return sign * (ageA - ageB);
      }
    }
  };
}

export type CacheTableDensity = "sparse" | "dense";

// Column layout — provider+detail flexes, the rest are fixed so sizes align.
const COLS = "grid-cols-[28px_1fr_90px_96px_64px]";

export function CacheTable({
  rows,
  selected,
  onToggle,
  density = "sparse",
}: {
  rows: CacheTableRow[];
  selected: Set<string>;
  onToggle: (id: string, next: boolean) => void;
  density?: CacheTableDensity;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "size",
    dir: "desc",
  });

  const sortedRows = useMemo(() => {
    const nowSecs = Date.now() / 1000;
    return [...rows].sort(makeComparator(sort.key, sort.dir, nowSecs));
  }, [rows, sort]);

  function headerClick(key: SortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: DEFAULT_DIR[key] },
    );
  }

  if (rows.length === 0) {
    return (
      <div className="p-8 text-center text-text-dim font-mono text-sm">
        (no entries)
      </div>
    );
  }

  return (
    <div className="font-mono text-[11px]">
      <div className={`grid ${COLS} gap-3 px-4 py-2 border-b border-border`}>
        <div />
        <SortHeader label="provider" col="provider" sort={sort} onClick={headerClick} />
        <SortHeader label="size" col="size" align="right" sort={sort} onClick={headerClick} />
        <SortHeader label="risk" col="risk" sort={sort} onClick={headerClick} />
        <SortHeader label="stale" col="stale" align="right" sort={sort} onClick={headerClick} />
      </div>
      {sortedRows.map((r) => {
        const isSelected = selected.has(r.id);
        const rowPad = density === "dense" ? "py-[3px]" : "py-[7px]";
        return (
          <div
            key={r.id}
            className={`grid ${COLS} gap-3 px-4 ${rowPad} items-center border-b border-border-subtle hover:bg-bg-elev-1`}
          >
            <Checkbox
              checked={isSelected}
              onChange={(next) => onToggle(r.id, next)}
              label={`select ${r.provider} ${r.label}`}
            />
            {density === "dense" ? (
              <div className="flex items-baseline gap-1.5 min-w-0">
                <ProviderIcon
                  slug={r.provider}
                  size={14}
                  className="shrink-0 self-center text-text-accent"
                />
                <span className="text-text-accent font-medium shrink-0">{r.provider}</span>
                <span
                  className="text-text-muted text-[10px] truncate"
                  title={r.path !== "—" ? r.path : r.label}
                >
                  {r.label}
                </span>
              </div>
            ) : (
              <div className="min-w-0 flex items-center gap-1.5">
                <ProviderIcon
                  slug={r.provider}
                  size={14}
                  className="shrink-0 text-text-accent"
                />
                <div className="min-w-0">
                  <div className="text-text-accent font-medium truncate">{r.provider}</div>
                  <div
                    className="text-text-muted text-[9.5px] mt-px truncate"
                    title={r.path !== "—" ? r.path : r.label}
                  >
                    {r.label}
                  </div>
                </div>
              </div>
            )}
            <div className="text-right tabular-nums font-medium">
              {humanBytes(r.size_bytes)}
            </div>
            <div>
              <RiskBadge risk={r.risk} />
            </div>
            <div className="text-right text-text-muted text-[10px] tabular-nums">
              {r.mtime === null ? "" : staleness(r.mtime)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SortHeader({
  label,
  col,
  align,
  sort,
  onClick,
}: {
  label: string;
  col: SortKey;
  align?: "right";
  sort: { key: SortKey; dir: SortDir };
  onClick: (col: SortKey) => void;
}) {
  const active = sort.key === col;
  // Small triangles sit on the baseline; full-size ones float above it.
  const caret = active ? (sort.dir === "asc" ? "▴" : "▾") : "";
  const ariaSort: "ascending" | "descending" | "none" = active
    ? sort.dir === "asc"
      ? "ascending"
      : "descending"
    : "none";
  return (
    <button
      type="button"
      onClick={() => onClick(col)}
      aria-sort={ariaSort}
      className={`flex items-center gap-1 uppercase tracking-widest text-[9.5px] transition-colors cursor-pointer hover:text-text ${
        active ? "text-text" : "text-text-muted"
      } ${align === "right" ? "justify-end" : ""}`}
    >
      <span>{label}</span>
      <span className="w-2 text-[8px] leading-none text-risk-reclaim">{caret}</span>
    </button>
  );
}
