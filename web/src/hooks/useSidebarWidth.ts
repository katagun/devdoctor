import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MIN_WIDTH,
  clampSidebarWidth,
  sidebarMaxWidth,
  useSettings,
} from "./useSettings";

const QUERY = "(max-width: 767px)";

/**
 * A store over one MediaQueryList for QUERY, whose `matches` is live. Reading
 * and subscribing through the same list keeps the two in step.
 */
function narrowViewportStore() {
  const mql =
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? null
      : window.matchMedia(QUERY);
  return {
    subscribe: (onChange: () => void): (() => void) => {
      mql?.addEventListener("change", onChange);
      return () => mql?.removeEventListener("change", onChange);
    },
    matches: (): boolean => mql?.matches ?? false,
  };
}

function notNarrowOnServer(): boolean {
  return false;
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
  // useSyncExternalStore reads the query while rendering and again once it has
  // subscribed, so a change in between is not missed.
  const [narrowViewport] = useState(narrowViewportStore);
  const forceCollapsedByViewport = useSyncExternalStore(
    narrowViewport.subscribe,
    narrowViewport.matches,
    notNarrowOnServer,
  );
  const [viewportWidth, setViewportWidth] = useState<number>(currentViewportWidth);

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
      const clamped = clampSidebarWidth(px, viewportWidth);
      const patch: { sidebarWidth: number; sidebarExpandedWidth?: number } = {
        sidebarWidth: clamped,
      };
      if (clamped > SIDEBAR_MIN_WIDTH) {
        patch.sidebarExpandedWidth = clamped;
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
