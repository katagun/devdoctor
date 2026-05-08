import { NavLink } from "react-router-dom";
import { NavIcon } from "@/components/NavIcon";
import { useSettings } from "@/hooks/useSettings";
import { domainToolItems, type ResourceDomain } from "@/lib/navigation";

export function DomainToolTabs({ domain }: { domain: ResourceDomain }) {
  const { settings } = useSettings();
  if (settings.toolNavigation !== "tabs") return null;
  const items = domainToolItems(domain);
  return (
    <div className="px-4 py-2 border-b border-border flex gap-2 bg-bg">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === `/${domain}`}
          className={({ isActive }) =>
            `px-2.5 py-[3px] rounded text-[10px] font-mono border transition-colors ${
              isActive
                ? "border-risk-reclaim bg-risk-reclaim/10 text-risk-reclaim"
                : "border-border text-text-dim hover:text-text"
            }`
          }
        >
          <span className="inline-flex items-center gap-1.5">
            <NavIcon icon={item.icon} size={13} />
            <span>{item.label}</span>
          </span>
        </NavLink>
      ))}
    </div>
  );
}
