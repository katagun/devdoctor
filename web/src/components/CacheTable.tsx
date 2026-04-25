import { useMemo, useState } from "react";
import { Checkbox } from "./Checkbox";
import { RiskBadge } from "./RiskBadge";
import { ProviderIcon } from "./ProviderIcon";
import { humanBytes, staleness, RiskValue } from "@/lib/format";
import { COLUMNS, type ColumnDef, type SortKey } from "./CacheTable/columns";
import { useHiddenColumns } from "@/hooks/useHiddenColumns";

export interface CacheTableRow {
  id: string;
  provider: string;
  label: string;
  path: string;
  size_bytes: number;
  risk: RiskValue;
  mtime: number | null;
  recipeHint: string;
  owner: string | null;
  group: string | null;
  perms: string | null;
}

type SortDir = "asc" | "desc";

const RISK_RANK: Record<RiskValue, number> = {
  safe: 0,
  reclaimable: 1,
  dangerous: 2,
};

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
  const { isVisible } = useHiddenColumns();
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "size",
    dir: "desc",
  });

  const visibleColumns: ColumnDef[] = useMemo(
    () => COLUMNS.filter((c) => isVisible(c.id)),
    [isVisible],
  );

  const gridTemplate = useMemo(
    () => `28px ${visibleColumns.map((c) => c.width).join(" ")}`,
    [visibleColumns],
  );

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
      <div
        className="grid gap-3 px-4 py-2 border-b border-border"
        style={{ gridTemplateColumns: gridTemplate }}
      >
        <div />
        {visibleColumns.map((col) =>
          col.sortable ? (
            <SortHeader
              key={col.id}
              label={col.label}
              col={col.id as SortKey}
              align={col.align}
              sort={sort}
              onClick={headerClick}
            />
          ) : (
            <div
              key={col.id}
              className={`uppercase tracking-widest text-[9.5px] text-text-muted ${
                col.align === "right" ? "flex justify-end" : ""
              }`}
            >
              {col.label}
            </div>
          ),
        )}
      </div>
      {sortedRows.map((r) => {
        const isSelected = selected.has(r.id);
        const rowPad = density === "dense" ? "py-[3px]" : "py-[7px]";
        return (
          <div
            key={r.id}
            className={`grid gap-3 px-4 ${rowPad} items-center border-b border-border-subtle hover:bg-bg-elev-1`}
            style={{ gridTemplateColumns: gridTemplate }}
          >
            <Checkbox
              checked={isSelected}
              onChange={(next) => onToggle(r.id, next)}
              label={`select ${r.provider} ${r.label}`}
            />
            {visibleColumns.map((col) => (
              <Cell key={col.id} col={col} row={r} density={density} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function Cell({
  col,
  row,
  density,
}: {
  col: ColumnDef;
  row: CacheTableRow;
  density: CacheTableDensity;
}) {
  switch (col.id) {
    case "provider":
      return density === "dense" ? (
        <div className="flex items-baseline gap-1.5 min-w-0">
          <ProviderIcon
            slug={row.provider}
            size={14}
            className="shrink-0 self-center text-text-accent"
          />
          <span className="text-text-accent font-medium shrink-0">{row.provider}</span>
          <span
            className="text-text-muted text-[10px] truncate"
            title={row.path !== "—" ? row.path : row.label}
          >
            {row.label}
          </span>
        </div>
      ) : (
        <div className="min-w-0 flex items-center gap-1.5">
          <ProviderIcon
            slug={row.provider}
            size={14}
            className="shrink-0 text-text-accent"
          />
          <div className="min-w-0">
            <div className="text-text-accent font-medium truncate">{row.provider}</div>
            <div
              className="text-text-muted text-[9.5px] mt-px truncate"
              title={row.path !== "—" ? row.path : row.label}
            >
              {row.label}
            </div>
          </div>
        </div>
      );
    case "size":
      return (
        <div className="text-right tabular-nums font-medium">
          {humanBytes(row.size_bytes)}
        </div>
      );
    case "risk":
      return (
        <div>
          <RiskBadge risk={row.risk} />
        </div>
      );
    case "stale":
      return (
        <div className="text-right text-text-muted text-[10px] tabular-nums">
          {row.mtime === null ? "" : staleness(row.mtime)}
        </div>
      );
    case "owner":
      return (
        <div className="text-text-dim text-[10.5px] truncate">
          {ownerPermsCell(row.owner, row.path)}
        </div>
      );
    case "perms":
      return (
        <div className="text-text-dim text-[10px] font-mono tabular-nums">
          {ownerPermsCell(row.perms, row.path)}
        </div>
      );
  }
}

// Logical entries (ollama models, docker images) report path=null which
// surfaces here as "—". Those rows have no owner/perms either; rendering
// "—" in three columns at once made them look broken. Treat null-on-a-pathless-row
// as deliberately blank; reserve "—" for path-backed rows where stat failed.
function ownerPermsCell(value: string | null, path: string): string {
  if (value !== null) return value;
  if (path === "—") return "";
  return "—";
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
