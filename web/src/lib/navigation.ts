export type ToolNavigation = "sidebar" | "tabs";
export type ResourceDomain = "disk" | "memory";

export interface ToolNavItem {
  to: string;
  glyph: string;
  label: string;
}

export const RESOURCE_ITEMS: ToolNavItem[] = [
  { to: "/disk", glyph: "◆", label: "disk" },
  { to: "/memory", glyph: "◫", label: "memory" },
];

export const DISK_TOOL_ITEMS: ToolNavItem[] = [
  { to: "/disk", glyph: "◆", label: "scan" },
  { to: "/disk/providers", glyph: "▣", label: "providers" },
  { to: "/disk/snapshots", glyph: "⏱", label: "snapshots" },
  { to: "/disk/history", glyph: "≡", label: "history" },
];

export const MEMORY_TOOL_ITEMS: ToolNavItem[] = [
  { to: "/memory", glyph: "◫", label: "live" },
  { to: "/memory/planner", glyph: "▤", label: "planner" },
  { to: "/memory/providers", glyph: "▣", label: "providers" },
  { to: "/memory/snapshots", glyph: "⏱", label: "snapshots" },
  { to: "/memory/history", glyph: "≡", label: "history" },
];

export function domainToolItems(domain: ResourceDomain): ToolNavItem[] {
  return domain === "disk" ? DISK_TOOL_ITEMS : MEMORY_TOOL_ITEMS;
}
