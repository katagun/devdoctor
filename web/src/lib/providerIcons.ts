// Resolver for provider-slug → icon. Consumed only by <ProviderIcon>.
// Phase C: simple-icons for brand marks, placeholder for everything else.
// PHASE-D: bundle unofficial logos under web/src/assets/provider-icons/ and
// register them in LOCAL_ICONS; resolver picks them up before the simple-icons
// fallback.

import {
  siDocker,
  siHuggingface,
  siOllama,
  siFirefox,
  siGooglechrome,
  siArc,
  siPython,
  siPypi,
  siPoetry,
  siAstral,
  siNpm,
  siHomebrew,
  siGradle,
  siApachemaven,
  siPytorch,
  siWeightsandbiases,
  siSpacy,
} from "simple-icons";

export type ResolvedIcon =
  | { kind: "simple-icon"; path: string; viewBox: "0 0 24 24" }
  | { kind: "local"; path: string; viewBox: string }
  | { kind: "placeholder" };

// Phase-D hook — empty in phase C.
const LOCAL_ICONS: Record<string, ResolvedIcon> = {};

// Reserved for exact-slug overrides when no prefix rule fits; unused in phase C.
const SIMPLE_ICON_MAP: Record<string, ResolvedIcon> = {};

const si = (icon: { path: string }): ResolvedIcon => ({
  kind: "simple-icon",
  path: icon.path,
  viewBox: "0 0 24 24",
});

// Prefix rules, evaluated top-to-bottom. A rule matches when
//   slug === rule.prefix || slug.startsWith(rule.prefix + "-")
// The dash boundary prevents "docker" from matching "dockerify-foo".
// Order matters: the first prefix that matches wins. Longer/more specific
// prefixes must come before shorter ones.
const PREFIX_RULES: ReadonlyArray<{ prefix: string; icon: ResolvedIcon }> = [
  { prefix: "arc-browser", icon: si(siArc) },
  { prefix: "chrome", icon: si(siGooglechrome) },
  { prefix: "firefox", icon: si(siFirefox) },
  { prefix: "docker", icon: si(siDocker) },
  { prefix: "huggingface", icon: si(siHuggingface) },
  { prefix: "ollama", icon: si(siOllama) },
  { prefix: "python-venvs", icon: si(siPython) },
  { prefix: "pip", icon: si(siPypi) },
  { prefix: "poetry", icon: si(siPoetry) },
  { prefix: "uv", icon: si(siAstral) },
  { prefix: "npm", icon: si(siNpm) },
  { prefix: "homebrew", icon: si(siHomebrew) },
  { prefix: "gradle", icon: si(siGradle) },
  { prefix: "maven", icon: si(siApachemaven) },
  { prefix: "torch", icon: si(siPytorch) },
  { prefix: "wandb", icon: si(siWeightsandbiases) },
  { prefix: "spacy", icon: si(siSpacy) },
];

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
