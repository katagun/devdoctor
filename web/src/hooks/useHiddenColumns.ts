import { useCallback, useMemo } from "react";
import type { ColumnId } from "@/components/CacheTable/columns";
import { COLUMNS } from "@/components/CacheTable/columns";
import { useSettings } from "./useSettings";

export interface UseHiddenColumnsResult {
  hiddenColumns: ReadonlySet<ColumnId>;
  isVisible: (id: ColumnId) => boolean;
  setHidden: (id: ColumnId, hidden: boolean) => void;
}

const NON_HIDEABLE = new Set<ColumnId>(
  COLUMNS.filter((c) => !c.hideable).map((c) => c.id),
);

export function useHiddenColumns(): UseHiddenColumnsResult {
  const { settings, update } = useSettings();

  const hiddenColumns = useMemo<ReadonlySet<ColumnId>>(
    () => new Set(settings.scanTableHiddenColumns),
    [settings.scanTableHiddenColumns],
  );

  const isVisible = useCallback(
    (id: ColumnId) => {
      if (NON_HIDEABLE.has(id)) return true;
      return !hiddenColumns.has(id);
    },
    [hiddenColumns],
  );

  const setHidden = useCallback(
    (id: ColumnId, hidden: boolean) => {
      if (NON_HIDEABLE.has(id)) return;
      const next = new Set(settings.scanTableHiddenColumns);
      if (hidden) next.add(id);
      else next.delete(id);
      update({ scanTableHiddenColumns: [...next] });
    },
    [settings.scanTableHiddenColumns, update],
  );

  return { hiddenColumns, isVisible, setHidden };
}
