import { NavLink } from "react-router-dom";
import { useSidebarCollapsed } from "@/hooks/useSidebarCollapsed";

const linkBase =
  "flex items-center px-3 py-1.5 rounded text-[10.5px] font-mono transition-colors";
const linkActive = "bg-bg-elev-2 text-text";
const linkIdle = "text-text-dim hover:bg-bg-elev-1";

function Item({
  to,
  glyph,
  label,
  count,
  collapsed,
}: {
  to: string;
  glyph: string;
  label: string;
  count?: number;
  collapsed: boolean;
}) {
  const alignment = collapsed ? "justify-center" : "justify-between";
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
          <span aria-hidden="true">{glyph}</span>
          <span className="sr-only">{label}</span>
        </>
      ) : (
        <>
          <span>
            <span aria-hidden="true">{glyph}</span> {label}
          </span>
          {count !== undefined && (
            <span className="text-text-muted text-[9.5px]">{count}</span>
          )}
        </>
      )}
    </NavLink>
  );
}

export function Sidebar() {
  const { collapsed } = useSidebarCollapsed();
  return (
    <aside className="bg-bg-elev-1 border-r border-border p-3 sticky top-0 h-screen">
      <div
        className={`flex gap-2 items-center pb-3 mb-4 border-b border-border ${
          collapsed ? "justify-center" : ""
        }`}
      >
        <span
          className="w-[7px] h-[7px] rounded-full bg-risk-reclaim"
          style={{ boxShadow: "0 0 10px var(--risk-reclaim)" }}
        />
        {!collapsed && (
          <span className="font-mono font-semibold text-[12px]">diskdoctor</span>
        )}
      </div>
      {!collapsed && (
        <div className="text-text-muted text-[9px] uppercase tracking-widest px-2 pb-1">
          workspace
        </div>
      )}
      <nav className="flex flex-col gap-0.5 mb-4">
        <Item to="/" glyph="◆" label="scan" collapsed={collapsed} />
        <Item to="/snapshots" glyph="⏱" label="snapshots" collapsed={collapsed} />
        <Item to="/history" glyph="≡" label="history" collapsed={collapsed} />
        <Item to="/providers" glyph="⚙" label="providers" collapsed={collapsed} />
        <Item to="/settings" glyph="⚡" label="settings" collapsed={collapsed} />
      </nav>
    </aside>
  );
}
