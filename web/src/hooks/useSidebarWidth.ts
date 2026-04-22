import { useCallback, useEffect, useState } from "react";
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MIN_WIDTH,
  clampSidebarWidth,
  sidebarMaxWidth,
  useSettings,
} from "./useSettings";

const QUERY = "(max-width: 767px)";

function getInitialMatch(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(QUERY).matches;
}

function currentViewportWidth(): number {
  if (typeof window === "undefined") return 1024;
  return window.innerWidth;
}

export interface UseSidebarWidthResult {
  width: number;
  collapsed: boolean;
  setWidth: (px: number) => void;
  toggle: () => void;
  forceCollapsedByViewport: boolean;
  maxWidth: number;
}

export function useSidebarWidth(): UseSidebarWidthResult {
  const { settings, update } = useSettings();
  const [forceCollapsedByViewport, setForced] = useState<boolean>(getInitialMatch);
  const [viewportWidth, setViewportWidth] = useState<number>(currentViewportWidth);

  // Migrate old sidebarCollapsed format on first render
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = localStorage.getItem("diskdoctor.settings.v1");
      if (!raw) return;
      const parsed = JSON.parse(raw);
      // If old sidebarCollapsed exists but new sidebarWidth doesn't, persist the migration
      if (typeof parsed.sidebarCollapsed === "boolean" && !("sidebarWidth" in parsed)) {
        update({
          sidebarWidth: parsed.sidebarCollapsed ? SIDEBAR_MIN_WIDTH : SIDEBAR_DEFAULT_WIDTH,
          sidebarExpandedWidth: SIDEBAR_DEFAULT_WIDTH,
        });
      }
    } catch {
      /* ignore */
    }
  }, [update]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(QUERY);
    setForced(mql.matches);
    const onChange = (e: MediaQueryListEvent | { matches: boolean }) => {
      setForced(e.matches);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const maxWidth = sidebarMaxWidth(viewportWidth);

  const setWidth = useCallback(
    (px: number) => {
      if (forceCollapsedByViewport) return;
      // Snap to minimum if dragging near collapse threshold
      const target = px < 80 ? SIDEBAR_MIN_WIDTH : clampSidebarWidth(px, viewportWidth);
      const patch: { sidebarWidth: number; sidebarExpandedWidth?: number } = {
        sidebarWidth: target,
      };
      if (target > SIDEBAR_MIN_WIDTH) {
        patch.sidebarExpandedWidth = target;
      }
      update(patch);
    },
    [forceCollapsedByViewport, viewportWidth, update],
  );

  const toggle = useCallback(() => {
    if (forceCollapsedByViewport) return;
    const collapsed = settings.sidebarWidth < 80;
    if (collapsed) {
      const target = clampSidebarWidth(
        settings.sidebarExpandedWidth || SIDEBAR_DEFAULT_WIDTH,
        viewportWidth,
      );
      update({ sidebarWidth: target });
    } else {
      update({ sidebarWidth: SIDEBAR_MIN_WIDTH });
    }
  }, [
    forceCollapsedByViewport,
    settings.sidebarWidth,
    settings.sidebarExpandedWidth,
    viewportWidth,
    update,
  ]);

  const effectiveWidth = forceCollapsedByViewport
    ? SIDEBAR_MIN_WIDTH
    : clampSidebarWidth(settings.sidebarWidth, viewportWidth);
  const collapsed = effectiveWidth < 80;

  return {
    width: effectiveWidth,
    collapsed,
    setWidth,
    toggle,
    forceCollapsedByViewport,
    maxWidth,
  };
}
