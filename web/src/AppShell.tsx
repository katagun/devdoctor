import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { UnsupportedDevice } from "./components/UnsupportedDevice";
import { useApplyTheme } from "./hooks/useApplyTheme";
import { useDeviceSupport } from "./lib/deviceSupport";
import { useSidebarWidth } from "./hooks/useSidebarWidth";

const MAC_LIKE = /^Mac/.test(
  typeof navigator !== "undefined" ? navigator.platform : "",
);

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export default function AppShell() {
  // All hooks are called unconditionally, before any early return, so the hook
  // call order is identical on every render (rules-of-hooks). The blocked gate
  // below only changes what's rendered, not which hooks run.
  useApplyTheme();
  const support = useDeviceSupport();
  const { width, toggle, forceCollapsedByViewport } = useSidebarWidth();

  useEffect(() => {
    function onKeydown(e: KeyboardEvent) {
      if (forceCollapsedByViewport) return;
      if (e.key !== "b" && e.key !== "B") return;
      const modifier = MAC_LIKE ? e.metaKey : e.ctrlKey;
      if (!modifier) return;
      if (e.altKey || e.shiftKey) return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      toggle();
    }
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, [toggle, forceCollapsedByViewport]);

  if (support.kind === "blocked") {
    return <UnsupportedDevice detected={support.detected} />;
  }

  return (
    <div
      className="min-h-screen grid bg-bg text-text font-sans"
      style={{ gridTemplateColumns: `${width}px 1fr` }}
    >
      <Sidebar />
      <main className="flex flex-col min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
