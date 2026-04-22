import { useCallback, useEffect, useRef, useState } from "react";
import { useSettings } from "./useSettings";

const QUERY = "(max-width: 767px)";

export interface UseSidebarCollapsedResult {
  collapsed: boolean;
  toggle: () => void;
  forceCollapsedByViewport: boolean;
}

export function useSidebarCollapsed(): UseSidebarCollapsedResult {
  const { settings, update } = useSettings();
  const [forceCollapsedByViewport, setForced] = useState<boolean>(false);
  const mqlRef = useRef<MediaQueryList | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(QUERY);
    mqlRef.current = mql;
    // Set initial state from the media query.
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
