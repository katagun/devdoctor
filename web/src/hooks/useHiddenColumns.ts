import { useCallback, useEffect, useMemo, useState } from "react";
import type { ColumnId } from "@/components/CacheTable/columns";
import { COLUMNS } from "@/components/CacheTable/columns";
import { defaultHiddenColumnsForViewport, useSettings } from "./useSettings";

export interface UseHiddenColumnsResult {
  hiddenColumns: ReadonlySet<ColumnId>;
  isVisible: (id: ColumnId) => boolean;
  setHidden: (id: ColumnId, hidden: boolean) => void;
}

const NON_HIDEABLE = new Set<ColumnId>(
  COLUMNS.filter((c) => !c.hideable).map((c) => c.id),
);

function readViewportWidth(): number {
  return typeof window === "undefined" ? 1024 : window.innerWidth;
}

function useViewportWidth(): number {
  const [width, setWidth] = useState<number>(readViewportWidth);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

export function useHiddenColumns(): UseHiddenColumnsResult {
  const { settings, update } = useSettings();
  const viewportWidth = useViewportWidth();

  const hiddenColumns = useMemo<ReadonlySet<ColumnId>>(() => {
    if (settings.scanTableColumnsCustomized) {
      return new Set(settings.scanTableHiddenColumns);
    }
    return new Set(defaultHiddenColumnsForViewport(viewportWidth));
  }, [
    settings.scanTableColumnsCustomized,
    settings.scanTableHiddenColumns,
    viewportWidth,
  ]);

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
      // Seed from the currently-effective set (viewport-derived OR stored)
      // so toggling a single column doesn't reset the others to defaults.
      const next = new Set(hiddenColumns);
      if (hidden) next.add(id);
      else next.delete(id);
      update({
        scanTableHiddenColumns: [...next],
        scanTableColumnsCustomized: true,
      });
    },
    [hiddenColumns, update],
  );

  return { hiddenColumns, isVisible, setHidden };
}
