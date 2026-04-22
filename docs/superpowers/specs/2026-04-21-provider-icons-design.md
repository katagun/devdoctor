# Provider icons — design

Date: 2026-04-21
Status: approved for implementation plan

## Goal

Show an official SVG mark next to every provider slug in the web UI (Scan table, Snapshots diff, Providers config page, Cleanup-wizard review). The icon is a visual anchor — the slug text stays present and authoritative; the icon is purely decorative.

## Slug namespace

`provider` in the API is a flat string. Two sources feed it:

- **Dynamic provider classes** — `docker`, `huggingface-hub`, `large-files`, `lm-studio-models`, `ollama`, `python-venvs`.
- **`data/paths.yaml` entries** — roughly 40 static entries: `uv-cache`, `pip-cache`, `poetry-cache`, `npm-cache`, `homebrew-downloads`, `lm-studio-extensions`, `huggingface-datasets-top`, `playwright`, `chrome-cache`, `firefox-cache`, `arc-browser-cache`, `docker-vm-disk`, `claude-vm-bundles`, `docker-installer`, `slack-service-worker`, `vscode-cache`, `gradle-caches`, `maven-repo`, `downloads`, `gpt4all-models`, `jan-models`, `msty-models`, `mlc-llm-cache`, `text-generation-webui-models`, `anythingllm-models`, `koboldcpp-models`, `whisper-models`, `vllm-cache`, `torch-hub-cache`, `stable-diffusion-webui-models`, `comfyui-models`, `invokeai-models`, `fooocus-models`, `localai-models`, `tabby-models`, `helix-cache`, `modelscope-cache`, `sentence-transformers-cache`, `spacy-cache`, `tiktoken-cache`, `wandb-cache`, `flair-cache`, `nltk-data`, `llama-cpp-cache`, `cortex-models`, `torchchat-models`, `open-webui-data`, `ramalama-store`.

Icon lookup is against this flat slug — never a nested provider/entry shape.

## Coverage policy

- **Phase C (this spec):** bundle real marks for slugs where `simple-icons` has one; render a neutral placeholder for everything else.
- **Phase D (deferred, doc only):** drop unofficial/hand-bundled SVGs into a local asset folder to cover indie tools (msty, jan, koboldcpp, cortex, ramalama, torchchat, open-webui, …). Spec documents the upgrade path so phase D is a one-line-per-slug change.

Explicitly rejected alternatives: inheriting a parent ecosystem's mark (misleading — InvokeAI is not PyTorch), categorized monograms (more moving parts than warranted at this stage).

## Color

Monochrome. Icons inherit `currentColor` so they track the existing palette (`text-text-accent`, `text-text-muted`, risk colors) row by row. No brand color, no hover state color, no per-icon theming. Rationale: the tables are dense `text-[11px]` mono grids with 2–3 accent colors — introducing 20+ saturated brand hexes would dominate the layout. Shape alone carries the recognition job.

## Architecture

One component + one resolver module + one asset folder:

```
web/src/components/ProviderIcon.tsx     React component (single public API)
web/src/lib/providerIcons.ts            slug → icon resolver + maps
web/src/assets/provider-icons/          phase-D local SVGs (empty in phase C)
```

`simple-icons` is imported only by `providerIcons.ts` — no other file touches it.

## Component API

```tsx
<ProviderIcon slug="docker" size={14} />
<ProviderIcon slug="firefox-cache" size={14} className="text-text-muted" />
```

Props:

- `slug: string` — the provider name from the API.
- `size?: number` — width and height in px; default `14`.
- `className?: string` — forwarded to the `<svg>`.

Output: a `<svg>` with `aria-hidden="true"` (decorative — the slug always appears as adjacent text). No wrapper element, no `role`. Fill is `currentColor`; stroke (placeholder only) is `currentColor`.

## Resolution algorithm

`providerIcons.ts` exports `resolveProviderIcon(slug: string): ResolvedIcon`.

Resolution order:

1. **Exact-slug local override** — `LOCAL_ICONS[slug]`. Empty map in phase C; phase-D entries land here.
2. **Exact-slug simple-icons map** — `SIMPLE_ICON_MAP[slug]`.
3. **Prefix match** — walks `PREFIX_RULES` in declared order, returns the first rule where `slug === rule.prefix || slug.startsWith(rule.prefix + "-")`. The dash boundary prevents a `docker` rule from matching a hypothetical `dockerify-foo`. Lets one rule cover `docker`, `docker-vm-disk`, `docker-installer` without listing each.
4. **Placeholder** — `PLACEHOLDER_ICON`.

Return shape:

```ts
type ResolvedIcon =
  | { kind: "simple-icon"; path: string; viewBox: "0 0 24 24" }
  | { kind: "local";       path: string; viewBox: string }
  | { kind: "placeholder"; }
```

`ProviderIcon` renders one `<svg>` per kind. All three kinds produce visually identical footprints at a given `size`.

## Initial slug → icon map (phase C)

Prefix rules, evaluated top-to-bottom. Anything not matched falls through to placeholder.

| Rule            | simple-icons import (per-file)        | Notes |
|-----------------|---------------------------------------|-------|
| `docker`        | `simple-icons/icons/docker`           | covers `docker`, `docker-vm-disk`, `docker-installer` |
| `huggingface`   | `simple-icons/icons/huggingface`      | covers `huggingface-hub`, `huggingface-datasets-top` |
| `ollama`        | `simple-icons/icons/ollama`           |       |
| `firefox`       | `simple-icons/icons/firefox`          | covers `firefox-cache` |
| `chrome`        | `simple-icons/icons/googlechrome`     | covers `chrome-cache` |
| `arc-browser`   | `simple-icons/icons/arc`              | verify at build; fallback to placeholder if missing |
| `slack`         | `simple-icons/icons/slack`            | covers `slack-service-worker` |
| `vscode`        | `simple-icons/icons/visualstudiocode` | covers `vscode-cache` |
| `python-venvs`  | `simple-icons/icons/python`           | python-venvs provider |
| `pip`           | `simple-icons/icons/pypi`             | covers `pip-cache` |
| `poetry`        | `simple-icons/icons/poetry`           |       |
| `uv`            | `simple-icons/icons/astral`           | astral is the `uv` vendor; verify; fallback to placeholder if missing |
| `npm`           | `simple-icons/icons/npm`              |       |
| `homebrew`      | `simple-icons/icons/homebrew`         |       |
| `gradle`        | `simple-icons/icons/gradle`           |       |
| `maven`         | `simple-icons/icons/apachemaven`      | covers `maven-repo` |
| `playwright`    | `simple-icons/icons/playwright`       |       |
| `torch`         | `simple-icons/icons/pytorch`          | covers `torch-hub-cache` |
| `wandb`         | `simple-icons/icons/weightsandbiases` | covers `wandb-cache` |
| `spacy`         | `simple-icons/icons/spacy`            | covers `spacy-cache` |

"Verify at build" means: at implementation time, confirm the icon exists in the installed `simple-icons` version. If not, keep the rule commented-out with a note; the slug renders placeholder — no runtime error.

Everything else (large-files, lm-studio-*, gpt4all-*, jan-*, msty-*, mlc-llm-*, text-generation-webui-*, anythingllm-*, koboldcpp-*, whisper-*, vllm-*, stable-diffusion-webui-*, comfyui-*, invokeai-*, fooocus-*, localai-*, tabby-*, helix-*, modelscope-*, sentence-transformers-*, tiktoken-*, flair-*, nltk-data, llama-cpp-*, cortex-*, torchchat-*, open-webui-*, ramalama-*, claude-vm-bundles, downloads) → placeholder.

## Placeholder

An outlined rounded square defined inline in `providerIcons.ts`:

```
<svg viewBox="0 0 24 24" width={size} height={size} ...>
  <rect x="3" y="3" width="18" height="18" rx="3"
        fill="none" stroke="currentColor" strokeWidth="2" />
</svg>
```

Occupies the same footprint at every size so column widths don't shift between resolved/unresolved slugs.

## Placements

| Surface | File | Change |
|---------|------|--------|
| Scan page | `web/src/components/CacheTable.tsx` | Render `<ProviderIcon slug={r.provider} size={14} />` immediately to the left of each `r.provider` span in the provider cell, with `gap-1.5`. No column template change — icon sits inside the existing cell's flex row. |
| Snapshots diff | `web/src/components/DiffTable.tsx` | Same pattern: 14px icon, `gap-1.5`, left of `r.provider` in the first column. |
| Providers config | `web/src/pages/Providers.tsx` | Add a 20px-wide icon column between the toggle and the name/description block. Grid template becomes `grid-cols-[60px_20px_1.3fr_0.8fr_1fr_0.6fr_0.9fr]` on both the header and the row. Icon is 16px centered in that cell. |
| Cleanup wizard review | `web/src/components/CleanupWizard/ReviewStep.tsx` | 12px icon before `{e.provider} / {e.label}`, `gap-1` inline. |

Not changed: `Sidebar.tsx` (nav), `TopStats.tsx` (aggregate), `RiskBadge.tsx`, wizard steps other than review.

## Accessibility

- Every icon is decorative: `aria-hidden="true"`, no `role`. Screen readers announce the adjacent slug text, never the icon.
- Placeholder uses identical a11y treatment.
- Icons never replace text and never act as interactive targets.

## Testing

- **New unit test** — `web/tests/unit/ProviderIcon.test.tsx`:
  - Renders a known-mapped slug (`docker`) → rendered `<path d>` matches the mapped simple-icon `path` field.
  - Unknown slug (`totally-made-up`) → renders the placeholder `<rect>`.
  - `size` prop controls both width and height attributes.
  - `className` is forwarded to the `<svg>`.
  - Prefix-rule slug (`docker-vm-disk`) resolves to the same icon as `docker`.
  - Dash-boundary prefix rule: a slug like `dockerify-foo` (no dash after `docker`) does NOT match the `docker` rule and falls through to placeholder.
- **Existing tests** — only `CacheTable.test.tsx` exists today. Augment it with one smoke assertion that a provider row contains a `<svg>` with `aria-hidden="true"`. No new `DiffTable` or `Providers` unit tests in this scope — those files have no existing test harness and adding them isn't load-bearing for the icon feature.
- **No snapshot tests** — simple-icons bumps would break them without signal.
- **No new e2e tests** — icons are presentational, no interactive flow changes.

## Dependencies and bundle

- Add `simple-icons` to `web/package.json` dependencies.
- Per-file imports (`import siDocker from 'simple-icons/icons/docker'`) ensure Vite tree-shakes everything not in `SIMPLE_ICON_MAP` / `PREFIX_RULES`.
- Estimated bundle impact: ~20 icons × ~500 B gzipped ≈ 10 KB to `dist/`.
- No backend changes.

## Phase-D upgrade path (documented, not implemented)

To bundle an unofficial/local logo later:

1. Save SVG as `web/src/assets/provider-icons/<slug>.svg`. Prefer single-path; multi-path is allowed but the component renders whatever the file contains inside a `<svg currentColor>` wrapper.
2. Add one entry to `LOCAL_ICONS` in `providerIcons.ts`: `"msty-models": () => import("@/assets/provider-icons/msty.svg?raw")` (or the equivalent Vite raw-import pattern chosen at phase-D time).
3. No consumer changes; no test changes beyond extending the ProviderIcon unit test for the new slug.

A `// PHASE-D:` comment in `providerIcons.ts` points at this procedure.

## Non-goals

- No backend changes: no icon field in `paths.yaml`, no API addition.
- No favicon or app-icon changes.
- No icons in `Sidebar.tsx` nav or `TopStats.tsx` aggregates.
- No brand-color rendering; no hover-color or active-row-color variants.
- No runtime fetching of icons from a CDN.
- No lazy/dynamic import of icons — the map is static so the bundler can tree-shake.

## Open questions resolved during brainstorming

- **Fallback for slugs without an official mark:** neutral placeholder now (phase C); bundle unofficial logos later (phase D). → placeholder + documented upgrade path.
- **Icon source:** `simple-icons` npm for brand marks, local folder for phase-D additions. → hybrid.
- **Color:** monochrome, inherits `currentColor`. → confirmed.
- **Placements:** Scan / Snapshots / Providers / Wizard-review; no Sidebar or TopStats. → confirmed.
- **Providers page layout:** dedicated 20px icon column (not inline) to keep names left-aligned across rows. → confirmed.
