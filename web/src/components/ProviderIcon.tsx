import { resolveProviderIcon } from "@/lib/providerIcons";

export interface ProviderIconProps {
  slug: string;
  size?: number;
  className?: string;
}

export function ProviderIcon({ slug, size = 14, className }: ProviderIconProps) {
  const icon = resolveProviderIcon(slug);

  if (icon.kind === "placeholder") {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        aria-hidden="true"
        className={className}
      >
        <rect x="3" y="3" width="18" height="18" rx="3" />
      </svg>
    );
  }

  // simple-icon and local both render as a single <path>. simple-icons is
  // always "0 0 24 24"; local SVGs may use a different viewBox (phase D).
  return (
    <svg
      width={size}
      height={size}
      viewBox={icon.viewBox}
      fill="currentColor"
      aria-hidden="true"
      className={className}
    >
      <path d={icon.path} />
    </svg>
  );
}
