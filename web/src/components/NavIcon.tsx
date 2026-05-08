import type { LucideIcon } from "lucide-react";

export function NavIcon({
  icon: Icon,
  size = 14,
}: {
  icon: LucideIcon;
  size?: number;
}) {
  return (
    <Icon
      aria-hidden="true"
      size={size}
      strokeWidth={1.75}
      className="shrink-0"
    />
  );
}
