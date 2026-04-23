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
  useApplyTheme();
  const support = useDeviceSupport();

  // Early return gate. A given browser session is either always blocked or
  // always supported — navigator.userAgent doesn't change within a mount —
  // so this never violates rules-of-hooks about consistent hook call order.
  if (support.kind === "blocked") {
    return <UnsupportedDevice detected={support.detected} />;
  }

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
