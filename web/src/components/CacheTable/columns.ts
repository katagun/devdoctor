export type ColumnId =
  | "provider"
  | "size"
  | "risk"
  | "stale"
  | "owner"
  | "perms";

export interface ColumnDef {
  id: ColumnId;
  label: string;
  width: string;          // CSS grid track, e.g. "1fr" or "90px"
  sortable: boolean;
  align?: "right";
  hideable: boolean;      // false only for provider (row identifier)
  defaultVisible: boolean;
}

export const COLUMNS: readonly ColumnDef[] = [
  { id: "provider", label: "provider", width: "1fr",  sortable: true,  hideable: false, defaultVisible: true },
  { id: "size",     label: "size",     width: "90px", sortable: true,  align: "right", hideable: true, defaultVisible: true },
  { id: "risk",     label: "risk",     width: "96px", sortable: true,  hideable: true, defaultVisible: true },
  { id: "stale",    label: "stale",    width: "64px", sortable: true,  align: "right", hideable: true, defaultVisible: true },
  { id: "owner",    label: "owner",    width: "80px", sortable: false, hideable: true, defaultVisible: false },
  { id: "perms",    label: "perms",    width: "90px", sortable: false, hideable: true, defaultVisible: false },
] as const;

/** Column ids that start hidden when the user has not customized the
 * scan table. OWNER and PERMS are forensic/diagnostic info that add no
 * signal on a single-user machine — power users can toggle them back on
 * via the columns picker. */
export const DEFAULT_HIDDEN_COLUMNS: readonly ColumnId[] = COLUMNS.filter(
  (c) => !c.defaultVisible,
).map((c) => c.id);

/** Subset of ColumnId values that can be sorted on. CacheTable's SortKey
 * type is derived from this so the sortable set stays in sync with the
 * registry. */
export type SortKey = "provider" | "size" | "risk" | "stale";
