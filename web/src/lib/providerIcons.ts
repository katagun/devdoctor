// Resolver for provider-slug → icon. Consumed only by <ProviderIcon>.
// Phase C: simple-icons for brand marks, placeholder for everything else.
// Phase D: hand-bundled logos under web/src/assets/provider-icons/ for brands
// that are either missing from simple-icons (Slack, Playwright, VS Code since
// v16) or poorly represented by the parent org's mark (uv → Astral).

import {
  siDocker,
  siHuggingface,
  siOllama,
  siFirefox,
  siGooglechrome,
  siArc,
  siCursor,
  siPython,
  siPypi,
  siPoetry,
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

// Phase-D hand-bundled paths. Source SVGs live at
// web/src/assets/provider-icons/<slug>.svg — path strings are duplicated here
// so the resolver can stay a pure synchronous function without a build-time
// SVG loader. Keep the two in sync when editing.
const UV_PATH =
  "M4 5v8a4 4 0 0 1 8 0V5h-1.5v8a2.5 2.5 0 0 0-5 0V5zM13.5 5h1.5l3 13h-1.5zM19 5h1.5l-3 13H16z";
const VSCODE_PATH = "M15 2 L5 12 L15 22 L18 22 L8 12 L18 2 Z";
// Generic monochrome stand-ins for brands not in simple-icons. Designed to
// be visually distinct from each other (and from the placeholder dot).
const SLACK_PATH =
  "M9 3h2v4H9zM13 3h2v4h-2zM9 17h2v4H9zM13 17h2v4h-2zM3 9h4v2H3zM17 9h4v2h-4zM3 13h4v2H3zM17 13h4v2h-4zM9 9h6v6H9z";
const PLAYWRIGHT_PATH =
  "M3 4h8v16H3zM13 4h8v16h-8zM5 6v12l5-3V9zM15 6v12l5-3V9z";
const LM_STUDIO_PATH =
  "M3 4h2v14h6v2H3zM13 4h2l3 8 3-8h2v16h-2V9l-3 8-3-8v11h-2z";
const DOWNLOADS_PATH = "M11 3h2v9h4l-5 6-5-6h4zM4 20h16v2H4z";

const localIcon = (path: string): ResolvedIcon => ({
  kind: "local",
  path,
  viewBox: "0 0 24 24",
});

// Reserved for exact-slug overrides when no prefix rule fits; unused today.
const SIMPLE_ICON_MAP: Record<string, ResolvedIcon> = {};

const si = (icon: { path: string }): ResolvedIcon => ({
  kind: "simple-icon",
  path: icon.path,
  viewBox: "0 0 24 24",
});

// Prefix rules, evaluated top-to-bottom. A rule matches when
//   slug === rule.prefix || slug.startsWith(rule.prefix + "-")
// The dash boundary prevents "docker" from matching "dockerify-foo".
// Order matters: the first prefix that matches wins. Local-bundled rules go
// above simple-icons rules so they take precedence.
const PREFIX_RULES: ReadonlyArray<{ prefix: string; icon: ResolvedIcon }> = [
  // Local-bundled (phase D).
  { prefix: "uv", icon: localIcon(UV_PATH) },
  { prefix: "vscode", icon: localIcon(VSCODE_PATH) },
  { prefix: "slack", icon: localIcon(SLACK_PATH) },
  { prefix: "playwright", icon: localIcon(PLAYWRIGHT_PATH) },
  { prefix: "lm-studio", icon: localIcon(LM_STUDIO_PATH) },
  { prefix: "downloads", icon: localIcon(DOWNLOADS_PATH) },
  // simple-icons brand marks.
  { prefix: "arc-browser", icon: si(siArc) },
  { prefix: "chrome", icon: si(siGooglechrome) },
  { prefix: "cursor", icon: si(siCursor) },
  { prefix: "firefox", icon: si(siFirefox) },
  { prefix: "docker", icon: si(siDocker) },
  { prefix: "huggingface", icon: si(siHuggingface) },
  { prefix: "ollama", icon: si(siOllama) },
  { prefix: "python-venvs", icon: si(siPython) },
  { prefix: "pip", icon: si(siPypi) },
  { prefix: "poetry", icon: si(siPoetry) },
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
  const exact = SIMPLE_ICON_MAP[slug];
  if (exact) return exact;

  for (const rule of PREFIX_RULES) {
    if (slug === rule.prefix || slug.startsWith(rule.prefix + "-")) {
      return rule.icon;
    }
  }

  return PLACEHOLDER_ICON;
}
