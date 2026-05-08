import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen, Settings } from "lucide-react";
import { NavIcon } from "@/components/NavIcon";
import { ResourceLabel } from "@/components/ResourceLabel";
import type { ToolNavItem } from "@/lib/navigation";
import { SidebarResizeHandle } from "@/components/SidebarResizeHandle";
import { useSidebarWidth } from "@/hooks/useSidebarWidth";
import { useSettings } from "@/hooks/useSettings";
import { APP_NAME } from "@/lib/brand";
import { DISK_TOOL_ITEMS, MEMORY_TOOL_ITEMS, RESOURCE_ITEMS } from "@/lib/navigation";
import { DISK_LABEL, MEMORY_LABEL } from "@/lib/resourceLabels";

const linkBase =
  "flex items-center px-3 py-1.5 rounded text-[10.5px] font-mono transition-colors";
const linkActive = "bg-bg-elev-2 text-text";
const linkIdle = "text-text-dim hover:bg-bg-elev-1";

function Item({ item, count, collapsed }: { item: ToolNavItem; count?: number; collapsed: boolean }) {
  const alignment = collapsed ? "justify-center" : "justify-between";
  const { to, icon, label } = item;
  return (
    <NavLink
      to={to}
      end={to === "/"}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        `${linkBase} ${alignment} ${isActive ? linkActive : linkIdle}`
      }
    >
      {collapsed ? (
        <>
          <NavIcon icon={icon} />
          <span className="sr-only">{label}</span>
        </>
      ) : (
        <>
          <span className="inline-flex items-center gap-2 min-w-0">
            <NavIcon icon={icon} />
            <span className="truncate">{label}</span>
          </span>
          {count !== undefined && (
            <span className="text-text-muted text-[9.5px]">{count}</span>
          )}
        </>
      )}
    </NavLink>
  );
}

function Section({
  title,
  items,
  collapsed,
}: {
  title: ReactNode;
  items: ToolNavItem[];
  collapsed: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      {!collapsed && (
        <div className="text-text-muted text-[9px] uppercase tracking-widest px-2 pb-1">
          {title}
        </div>
      )}
      {items.map((item) => (
        <Item
          key={item.to}
          item={item}
          collapsed={collapsed}
        />
      ))}
    </div>
  );
}

function ChevronToggle({
  collapsed,
  onClick,
}: {
  collapsed: boolean;
  onClick: () => void;
}) {
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-expanded={!collapsed}
      className="text-text-muted hover:text-text text-[11px] px-1 leading-none"
    >
      <NavIcon icon={collapsed ? PanelLeftOpen : PanelLeftClose} size={14} />
    </button>
  );
}

export function Sidebar() {
  const { width, collapsed, setWidth, toggle, maxWidth, forceCollapsedByViewport } =
    useSidebarWidth();
  const { settings } = useSettings();
  const showTools = settings.toolNavigation === "sidebar";

  return (
    <aside className="bg-bg-elev-1 border-r border-border p-3 sticky top-0 h-screen relative">
      <div
        className={`flex gap-2 items-center pb-3 mb-4 border-b border-border ${
          collapsed ? "flex-col" : ""
        }`}
      >
        <div className={`flex items-center gap-2 ${collapsed ? "" : "flex-1"}`}>
          <span
            className="w-[7px] h-[7px] rounded-full bg-risk-reclaim"
            style={{ boxShadow: "0 0 10px var(--risk-reclaim)" }}
          />
          {!collapsed && (
            <span className="font-mono font-semibold text-[12px]">{APP_NAME}</span>
          )}
        </div>
        {!forceCollapsedByViewport && (
          <ChevronToggle collapsed={collapsed} onClick={toggle} />
        )}
      </div>
      <nav className="flex flex-col gap-3 mb-4" aria-label="Primary">
        <Section
          title="resources"
          collapsed={collapsed}
          items={RESOURCE_ITEMS}
        />
        {showTools && (
          <>
            <Section
              title={<ResourceLabel resource="disk" label={`${DISK_LABEL} tools`} size={12} />}
              collapsed={collapsed}
              items={DISK_TOOL_ITEMS.filter((item) => item.label !== "scan")}
            />
            <Section
              title={<ResourceLabel resource="memory" label={`${MEMORY_LABEL} tools`} size={12} />}
              collapsed={collapsed}
              items={MEMORY_TOOL_ITEMS.filter((item) => item.label !== "live")}
            />
          </>
        )}
        <Section
          title="app"
          collapsed={collapsed}
          items={[
            { to: "/settings", icon: Settings, label: "settings" },
          ]}
        />
      </nav>
      <SidebarResizeHandle
        width={width}
        maxWidth={maxWidth}
        setWidth={setWidth}
        finalize={setWidth}
        hidden={forceCollapsedByViewport}
      />
    </aside>
  );
}
