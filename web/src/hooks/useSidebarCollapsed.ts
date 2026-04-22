import { useCallback, useEffect, useState } from "react";
import { useSettings } from "./useSettings";

const QUERY = "(max-width: 767px)";

function getInitialMatch(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(QUERY).matches;
}

export interface UseSidebarCollapsedResult {
  collapsed: boolean;
  toggle: () => void;
  forceCollapsedByViewport: boolean;
}

export function useSidebarCollapsed(): UseSidebarCollapsedResult {
  const { settings, update } = useSettings();
  // Synchronous lazy initialiser avoids a one-frame expanded-sidebar flash on
  // narrow viewports when the app first mounts below the breakpoint.
  const [forceCollapsedByViewport, setForced] = useState<boolean>(getInitialMatch);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(QUERY);
    // Re-read in case the viewport changed between module init and mount.
    setForced(mql.matches);
    const onChange = (e: MediaQueryListEvent | { matches: boolean }) => {
      setForced(e.matches);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    if (forceCollapsedByViewport) return;
    update({ sidebarCollapsed: !settings.sidebarCollapsed });
  }, [forceCollapsedByViewport, settings.sidebarCollapsed, update]);

  const collapsed = forceCollapsedByViewport || settings.sidebarCollapsed;
  return { collapsed, toggle, forceCollapsedByViewport };
}
