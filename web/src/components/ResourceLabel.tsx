import { HardDrive, MemoryStick } from "lucide-react";
import { NavIcon } from "@/components/NavIcon";

const RESOURCE_ICONS = {
  disk: HardDrive,
  memory: MemoryStick,
} as const;

export function ResourceLabel({
  resource,
  label,
  size = 14,
}: {
  resource: keyof typeof RESOURCE_ICONS;
  label: string;
  size?: number;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 min-w-0">
      <NavIcon icon={RESOURCE_ICONS[resource]} size={size} />
      <span className="truncate">{label}</span>
    </span>
  );
}
