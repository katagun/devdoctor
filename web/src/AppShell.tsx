import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { useApplyTheme } from "./hooks/useApplyTheme";
import { useSidebarCollapsed } from "./hooks/useSidebarCollapsed";

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
  const { collapsed, toggle, forceCollapsedByViewport } = useSidebarCollapsed();

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

  const gridCols = collapsed ? "grid-cols-[48px_1fr]" : "grid-cols-[180px_1fr]";

  return (
    <div className={`min-h-screen grid ${gridCols} bg-bg text-text font-sans`}>
      <Sidebar />
      <main className="flex flex-col min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
