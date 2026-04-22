// Resolver for provider-slug → icon. Consumed only by <ProviderIcon>.
// Phase C: simple-icons for brand marks, placeholder for everything else.
// PHASE-D: bundle unofficial logos under web/src/assets/provider-icons/ and
// register them in LOCAL_ICONS; resolver picks them up before the simple-icons
// fallback.

import { siDocker } from "simple-icons";

export type ResolvedIcon =
  | { kind: "simple-icon"; path: string; viewBox: "0 0 24 24" }
  | { kind: "local"; path: string; viewBox: string }
  | { kind: "placeholder" };

// Phase-D hook — empty in phase C.
const LOCAL_ICONS: Record<string, ResolvedIcon> = {};

// Exact slug → simple-icons. Populated in Task 6.
const SIMPLE_ICON_MAP: Record<string, ResolvedIcon> = {
  docker: { kind: "simple-icon", path: siDocker.path, viewBox: "0 0 24 24" },
};

// Prefix rules, evaluated top-to-bottom. A rule matches when
//   slug === rule.prefix || slug.startsWith(rule.prefix + "-")
// The dash boundary prevents "docker" from matching "dockerify-foo".
// Populated in Task 6.
const PREFIX_RULES: ReadonlyArray<{ prefix: string; icon: ResolvedIcon }> = [];

export const PLACEHOLDER_ICON: ResolvedIcon = { kind: "placeholder" };

export function resolveProviderIcon(slug: string): ResolvedIcon {
  const local = LOCAL_ICONS[slug];
  if (local) return local;

  const exact = SIMPLE_ICON_MAP[slug];
  if (exact) return exact;

  for (const rule of PREFIX_RULES) {
    if (slug === rule.prefix || slug.startsWith(rule.prefix + "-")) {
      return rule.icon;
    }
  }

  return PLACEHOLDER_ICON;
}
