import { resolveProviderIcon } from "@/lib/providerIcons";

export interface ProviderIconProps {
  slug: string;
  size?: number;
  className?: string;
}

export function ProviderIcon({ slug, size = 14, className }: ProviderIconProps) {
  const icon = resolveProviderIcon(slug);

  if (icon.kind === "placeholder") {
    // Subtle filled dot — distinct from the unchecked-checkbox shape that
    // also appears in these table rows. Centered in the same footprint so
    // column alignment matches resolved icons.
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden="true"
        className={className}
        opacity={0.4}
      >
        <circle cx="12" cy="12" r="2" />
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
