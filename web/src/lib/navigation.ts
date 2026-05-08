import {
  Boxes,
  Clock,
  HardDrive,
  History,
  LayoutDashboard,
  ListChecks,
  MemoryStick,
  type LucideIcon,
} from "lucide-react";

export type ToolNavigation = "sidebar" | "tabs";
export type ResourceDomain = "disk" | "memory";
export type LandingPage = "dashboard" | ResourceDomain;

export interface ToolNavItem {
  to: string;
  icon: LucideIcon;
  label: string;
}

export const RESOURCE_ITEMS: ToolNavItem[] = [
  { to: "/dashboard", icon: LayoutDashboard, label: "dashboard" },
  { to: "/disk", icon: HardDrive, label: "disk" },
  { to: "/memory", icon: MemoryStick, label: "memory" },
];

export const DISK_TOOL_ITEMS: ToolNavItem[] = [
  { to: "/disk", icon: HardDrive, label: "scan" },
  { to: "/disk/providers", icon: Boxes, label: "providers" },
  { to: "/disk/snapshots", icon: Clock, label: "snapshots" },
  { to: "/disk/history", icon: History, label: "history" },
];

export const MEMORY_TOOL_ITEMS: ToolNavItem[] = [
  { to: "/memory", icon: MemoryStick, label: "live" },
  { to: "/memory/planner", icon: ListChecks, label: "planner" },
  { to: "/memory/providers", icon: Boxes, label: "providers" },
  { to: "/memory/snapshots", icon: Clock, label: "snapshots" },
  { to: "/memory/history", icon: History, label: "history" },
];

export function domainToolItems(domain: ResourceDomain): ToolNavItem[] {
  return domain === "disk" ? DISK_TOOL_ITEMS : MEMORY_TOOL_ITEMS;
}
