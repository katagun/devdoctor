# Provider Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a monochrome `simple-icons` SVG next to every provider slug in the web UI (Scan table, Snapshots diff, Providers config page, Cleanup-wizard review). Unmapped slugs render a neutral placeholder; a phase-D upgrade path is kept documented but not implemented.

**Import pattern note (post-Task-1 amendment):** `simple-icons` v16 deprecated the per-subpath import (`simple-icons/icons/docker`) in favor of the barrel (`import { siDocker } from "simple-icons"`). This plan uses the v16 barrel form throughout; `sideEffects: false` in the package's `package.json` keeps Vite/Rollup tree-shaking. Also post-Task-1: `slack`, `visualstudiocode`, and `playwright` no longer ship in the simple-icons brand set (confirmed against the installed 16.17.0), so those slugs fall through to placeholder in phase C — no rules for them in Task 6.

**Architecture:** One React component (`<ProviderIcon>`) and one resolver module (`providerIcons.ts`). The resolver walks an ordered chain (exact local override → exact simple-icons map → dash-boundary prefix rule → placeholder) and returns a tagged discriminated-union that the component renders as a single `<svg>`. No backend changes.

**Tech Stack:** TypeScript, React 18, Vite, Vitest + @testing-library/react, Tailwind 4, `simple-icons` npm (new dep).

**Source spec:** `docs/superpowers/specs/2026-04-21-provider-icons-design.md` — read it before starting Task 1.

**Working directory for every command below:** `/Users/shamil/projects/github/katagun/diskdoctor/web` unless stated otherwise. The Python backend is untouched by this plan.

---

## Task 1: Install simple-icons and verify slug availability

**Files:**
- Modify: `web/package.json` (add `simple-icons` dependency)
- Modify: `web/package-lock.json` (auto-generated)

**Context:** `simple-icons` is a large package (3k+ icons, ~10 MB installed). Per-subpath imports (`simple-icons/icons/docker`) land only the ones used in the bundle. Some icons referenced in the spec may not be present in the installed version — we probe for them now so later tasks can either include a rule or leave it commented out.

- [ ] **Step 1: Install the dependency**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm install simple-icons
```

Expected: `package.json` and `package-lock.json` updated; `simple-icons` appears under `"dependencies"`. No errors.

- [ ] **Step 2: Probe slug availability**

The spec's 20 prefix rules reference these simple-icons subpaths. Verify each file exists on disk:

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
for slug in docker huggingface ollama firefox googlechrome arc slack visualstudiocode python pypi poetry astral npm homebrew gradle apachemaven playwright pytorch weightsandbiases spacy; do
  if [ -e "node_modules/simple-icons/icons/${slug}.js" ] || [ -e "node_modules/simple-icons/icons/${slug}.mjs" ]; then
    echo "OK    ${slug}"
  else
    echo "MISS  ${slug}"
  fi
done
```

Expected: a list with `OK` for most and possibly `MISS` for `arc`, `astral`, or `ollama` depending on the installed version. Write down the MISS list — Task 6 will either comment those rules out or resolve via a different simple-icons slug (e.g. if `astral` is missing but `uv` exists, use `uv`; if none exists, leave the `uv-*` prefix unmapped so it falls through to placeholder).

- [ ] **Step 3: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/package.json web/package-lock.json
git commit -m "build(web): add simple-icons dependency"
```

Expected: one commit added; `git status` clean for those files.

---

## Task 2: Scaffold types, placeholder resolver, and component (TDD — unknown slug → placeholder)

**Files:**
- Create: `web/src/lib/providerIcons.ts`
- Create: `web/src/components/ProviderIcon.tsx`
- Create: `web/tests/unit/ProviderIcon.test.tsx`
- Create: `web/src/types/simple-icons.d.ts` (only if Step 3 typechecks fail — see note)

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/ProviderIcon.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ProviderIcon } from "@/components/ProviderIcon";

describe("ProviderIcon", () => {
  it("renders a placeholder rect for an unknown slug", () => {
    const { container } = render(<ProviderIcon slug="totally-made-up-slug" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.hasAttribute("role")).toBe(false);
    expect(container.querySelector("rect")).not.toBeNull();
    expect(container.querySelector("path")).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test and watch it fail**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: FAIL with a resolution error on `@/components/ProviderIcon` (file doesn't exist yet).

- [ ] **Step 3: Create the resolver module**

Create `web/src/lib/providerIcons.ts`:

```ts
// Resolver for provider-slug → icon. Consumed only by <ProviderIcon>.
// Phase C: simple-icons for brand marks, placeholder for everything else.
// PHASE-D: bundle unofficial logos under web/src/assets/provider-icons/ and
// register them in LOCAL_ICONS; resolver picks them up before the simple-icons
// fallback.

export type ResolvedIcon =
  | { kind: "simple-icon"; path: string; viewBox: "0 0 24 24" }
  | { kind: "local"; path: string; viewBox: string }
  | { kind: "placeholder" };

// Phase-D hook — empty in phase C.
const LOCAL_ICONS: Record<string, ResolvedIcon> = {};

// Exact slug → simple-icons. Populated in Task 6.
const SIMPLE_ICON_MAP: Record<string, ResolvedIcon> = {};

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
```

Create `web/src/components/ProviderIcon.tsx`:

```tsx
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
```

- [ ] **Step 4: Run the test and watch it pass**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: PASS — 1 test, 0 failures.

- [ ] **Step 5: Run the typechecker**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/.worktrees/provider-icons/web
npm run typecheck
```

Expected: PASS (no `tsc` output, exit 0). `simple-icons` v16 ships its own types at the package root, so no `.d.ts` shim is needed for the barrel imports used in Task 3+.

- [ ] **Step 6: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/.worktrees/provider-icons
git add web/src/lib/providerIcons.ts web/src/components/ProviderIcon.tsx web/tests/unit/ProviderIcon.test.tsx
git commit -m "feat(web): scaffold ProviderIcon with placeholder fallback"
```

Expected: one commit added.

---

## Task 3: First exact-slug mapping — `docker` (TDD)

**Files:**
- Modify: `web/src/lib/providerIcons.ts`
- Modify: `web/tests/unit/ProviderIcon.test.tsx`

- [ ] **Step 1: Add the failing test**

Append to the `describe("ProviderIcon", ...)` block in `web/tests/unit/ProviderIcon.test.tsx`:

```tsx
import { siDocker } from "simple-icons";

// ... inside describe:
  it("renders the simple-icons docker path for slug 'docker'", () => {
    const { container } = render(<ProviderIcon slug="docker" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siDocker.path);
    expect(container.querySelector("rect")).toBeNull();
  });
```

(Add the `import { siDocker } from "simple-icons";` line at the top of the file alongside the existing imports.)

- [ ] **Step 2: Run the test and watch it fail**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/.worktrees/provider-icons/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: FAIL — the `"docker"` slug still resolves to placeholder, so `path` is null and the assertion fails with `Expected 'null' to be '<long path string>'`.

- [ ] **Step 3: Wire docker into `SIMPLE_ICON_MAP`**

Edit `web/src/lib/providerIcons.ts`. At the top of the file, add:

```ts
import { siDocker } from "simple-icons";
```

Replace:

```ts
const SIMPLE_ICON_MAP: Record<string, ResolvedIcon> = {};
```

with:

```ts
const SIMPLE_ICON_MAP: Record<string, ResolvedIcon> = {
  docker: { kind: "simple-icon", path: siDocker.path, viewBox: "0 0 24 24" },
};
```

- [ ] **Step 4: Run the test and watch it pass**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: PASS — 2 tests, 0 failures.

- [ ] **Step 5: Typecheck**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/.worktrees/provider-icons/web
npm run typecheck
```

Expected: PASS. (simple-icons v16 ships types at the package root; the barrel import resolves types automatically.)

- [ ] **Step 6: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/.worktrees/provider-icons
git add web/src/lib/providerIcons.ts web/tests/unit/ProviderIcon.test.tsx
git commit -m "feat(web): wire ProviderIcon to simple-icons for 'docker'"
```

---

## Task 4: Prefix-rule matching with dash-boundary (TDD)

**Files:**
- Modify: `web/src/lib/providerIcons.ts`
- Modify: `web/tests/unit/ProviderIcon.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append to the `describe("ProviderIcon", ...)` block:

```tsx
  it("prefix rule matches slug with dash boundary (docker-vm-disk → docker)", () => {
    const { container } = render(<ProviderIcon slug="docker-vm-disk" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siDocker.path);
  });

  it("prefix rule does NOT match when no dash follows (dockerify-foo → placeholder)", () => {
    const { container } = render(<ProviderIcon slug="dockerify-foo" />);
    expect(container.querySelector("rect")).not.toBeNull();
    expect(container.querySelector("path")).toBeNull();
  });
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: `docker-vm-disk` test FAILS (still placeholder); `dockerify-foo` test PASSES incidentally (no rule matches it yet). Both tests must pass after Step 3.

- [ ] **Step 3: Add the first prefix rule**

Edit `web/src/lib/providerIcons.ts`. Replace:

```ts
const PREFIX_RULES: ReadonlyArray<{ prefix: string; icon: ResolvedIcon }> = [];
```

with:

```ts
const PREFIX_RULES: ReadonlyArray<{ prefix: string; icon: ResolvedIcon }> = [
  { prefix: "docker", icon: { kind: "simple-icon", path: siDocker.path, viewBox: "0 0 24 24" } },
];
```

Also remove the now-redundant exact entry for `docker` in `SIMPLE_ICON_MAP` — the prefix rule covers it:

```ts
const SIMPLE_ICON_MAP: Record<string, ResolvedIcon> = {};
```

(The exact map stays in the module; Task 6 may populate it for slugs that don't fit any prefix.)

- [ ] **Step 4: Run tests and watch them pass**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: PASS — 4 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/src/lib/providerIcons.ts web/tests/unit/ProviderIcon.test.tsx
git commit -m "feat(web): ProviderIcon prefix rules with dash-boundary match"
```

---

## Task 5: `size` and `className` prop contracts (TDD)

**Files:**
- Modify: `web/tests/unit/ProviderIcon.test.tsx`

The implementation already supports both props; this task locks the contract with tests.

- [ ] **Step 1: Add the failing tests**

Append to the `describe("ProviderIcon", ...)` block:

```tsx
  it("applies the size prop to width and height", () => {
    const { container } = render(<ProviderIcon slug="docker" size={20} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("20");
    expect(svg?.getAttribute("height")).toBe("20");
  });

  it("defaults to size=14 when omitted", () => {
    const { container } = render(<ProviderIcon slug="docker" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("14");
    expect(svg?.getAttribute("height")).toBe("14");
  });

  it("forwards className to the <svg>", () => {
    const { container } = render(
      <ProviderIcon slug="docker" className="text-text-muted custom-mark" />,
    );
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-text-muted");
    expect(svg?.className.baseVal).toContain("custom-mark");
  });

  it("forwards className on the placeholder path too", () => {
    const { container } = render(
      <ProviderIcon slug="no-such-slug" className="text-text-dim" />,
    );
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-text-dim");
  });
```

- [ ] **Step 2: Run tests and watch them pass**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: PASS — 8 tests, 0 failures (the implementation from Task 2 already satisfies these contracts).

- [ ] **Step 3: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/tests/unit/ProviderIcon.test.tsx
git commit -m "test(web): lock ProviderIcon size + className contract"
```

---

## Task 6: Populate full phase-C slug map

**Files:**
- Modify: `web/src/lib/providerIcons.ts`

Load the remaining prefix rules from the spec. A single barrel import keeps only the named icons in the bundle thanks to `simple-icons`'s `sideEffects: false` + ESM exports.

**Three rules dropped from the original spec** after Task 1 confirmed they were removed from simple-icons v16: `slack`, `vscode` (visualstudiocode), `playwright`. Those provider slugs (`slack-service-worker`, `vscode-cache`, `playwright`) will render the placeholder in phase C — exactly the intended fallback. Phase-D can bundle local SVGs later.

- [ ] **Step 1: Replace the imports block**

At the top of `web/src/lib/providerIcons.ts`, replace the current `import { siDocker } from "simple-icons";` line with the full barrel:

```ts
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
```

All 17 of these were verified present in Task 1 against simple-icons 16.17.0. If a future `npm install` bumps simple-icons to a version that drops any of them, `tsc` will surface the missing export at build time — comment the import + its PREFIX_RULES entry out, the affected slug falls to placeholder.

- [ ] **Step 2: Replace `PREFIX_RULES` with the full ordered list**

Replace the current `PREFIX_RULES = [...]` block with:

```ts
const si = (icon: { path: string }): ResolvedIcon => ({
  kind: "simple-icon",
  path: icon.path,
  viewBox: "0 0 24 24",
});

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
```

Rules for `slack`, `vscode`, `playwright` are intentionally absent — the corresponding slugs (`slack-service-worker`, `vscode-cache`, `playwright`) render the placeholder in phase C. Phase-D can bundle local SVGs.

`arc-browser` precedes `chrome`/`firefox` since it's the more specific prefix among browsers; within the rest, order matters only when one prefix is a prefix of another — which isn't the case here, but the explicit ordering makes future additions safer.

- [ ] **Step 3: Run all tests**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: PASS — 8 tests, 0 failures. None of the earlier behaviours regress.

- [ ] **Step 4: Add two coverage tests to guard the map**

Append to the `describe("ProviderIcon", ...)` block:

```tsx
import { siFirefox, siPytorch } from "simple-icons";

  it("firefox-cache slug resolves to the firefox icon", () => {
    const { container } = render(<ProviderIcon slug="firefox-cache" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siFirefox.path);
  });

  it("torch-hub-cache slug resolves to the pytorch icon", () => {
    const { container } = render(<ProviderIcon slug="torch-hub-cache" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siPytorch.path);
  });
```

(Move the `import` lines to the top of the file alongside the existing ones.)

- [ ] **Step 5: Run tests**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/ProviderIcon.test.tsx
```

Expected: PASS — 10 tests, 0 failures.

- [ ] **Step 6: Typecheck**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/src/lib/providerIcons.ts web/tests/unit/ProviderIcon.test.tsx
git commit -m "feat(web): populate phase-C provider icon map"
```

---

## Task 7: Integrate into `CacheTable` + augment existing test

**Files:**
- Modify: `web/src/components/CacheTable.tsx` (dense branch ~lines 130-139, sparse branch ~lines 140-150)
- Modify: `web/tests/unit/CacheTable.test.tsx`

- [ ] **Step 1: Augment the existing test first**

Edit `web/tests/unit/CacheTable.test.tsx`. In the top-of-file imports, the existing import stays. Add a new test to the `describe("CacheTable", ...)` block (after the existing tests):

```tsx
  it("renders a decorative icon next to each provider slug", () => {
    const { container } = render(
      <CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />,
    );
    const icons = container.querySelectorAll('svg[aria-hidden="true"]');
    // One icon per row (2 rows). The Checkbox doesn't contribute an
    // aria-hidden svg today, but if that ever changes this assertion
    // documents the intent clearly.
    expect(icons.length).toBeGreaterThanOrEqual(rows.length);
  });
```

- [ ] **Step 2: Run existing tests and watch the new one fail**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run tests/unit/CacheTable.test.tsx
```

Expected: 6 existing tests PASS, the new test FAILS because no icon is rendered yet.

- [ ] **Step 3: Import `ProviderIcon` in `CacheTable`**

Edit `web/src/components/CacheTable.tsx`. Add to the imports block at the top:

```tsx
import { ProviderIcon } from "./ProviderIcon";
```

- [ ] **Step 4: Insert the icon in the dense branch**

Replace the block currently at lines 130-139 (the `{density === "dense" ? (` branch, rendering `<span>{r.provider}</span>` and `<span>{r.label}</span>`) with:

```tsx
            {density === "dense" ? (
              <div className="flex items-baseline gap-1.5 min-w-0">
                <ProviderIcon
                  slug={r.provider}
                  size={14}
                  className="shrink-0 self-center text-text-accent"
                />
                <span className="text-text-accent font-medium shrink-0">{r.provider}</span>
                <span
                  className="text-text-muted text-[10px] truncate"
                  title={r.path !== "—" ? r.path : r.label}
                >
                  {r.label}
                </span>
              </div>
            ) : (
```

(Changes: `gap-2` → `gap-1.5`; the `<ProviderIcon>` sits first. `self-center` compensates for `items-baseline` on the flex row.)

- [ ] **Step 5: Insert the icon in the sparse branch**

Replace the `: (` branch (sparse layout, currently lines ~140-150) with:

```tsx
              <div className="min-w-0 flex items-center gap-1.5">
                <ProviderIcon
                  slug={r.provider}
                  size={14}
                  className="shrink-0 text-text-accent"
                />
                <div className="min-w-0">
                  <div className="text-text-accent font-medium truncate">{r.provider}</div>
                  <div
                    className="text-text-muted text-[9.5px] mt-px truncate"
                    title={r.path !== "—" ? r.path : r.label}
                  >
                    {r.label}
                  </div>
                </div>
              </div>
```

(Changes: outer `<div>` becomes a flex row so the 14px icon vertically-centers against the two-line label block; inner `<div className="min-w-0">` preserves the existing truncation behavior.)

- [ ] **Step 6: Run all tests**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run
```

Expected: PASS — all `ProviderIcon` tests still pass; all `CacheTable` tests including the new smoke test pass.

- [ ] **Step 7: Typecheck**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/src/components/CacheTable.tsx web/tests/unit/CacheTable.test.tsx
git commit -m "feat(web): provider icons in CacheTable (Scan page)"
```

---

## Task 8: Integrate into `DiffTable`

**Files:**
- Modify: `web/src/components/DiffTable.tsx`

No existing unit test for `DiffTable`; per the spec, this plan doesn't add one — the `ProviderIcon` unit tests already cover the icon resolution, and the integration is visually trivial.

- [ ] **Step 1: Import `ProviderIcon`**

Edit `web/src/components/DiffTable.tsx`. Add to the imports:

```tsx
import { ProviderIcon } from "./ProviderIcon";
```

- [ ] **Step 2: Insert the icon in the provider cell**

Replace line 21:

```tsx
            <div className="text-text-accent">{r.provider}</div>
```

with:

```tsx
            <div className="flex items-center gap-1.5 text-text-accent min-w-0">
              <ProviderIcon slug={r.provider} size={14} className="shrink-0" />
              <span className="truncate">{r.provider}</span>
            </div>
```

(The icon inherits `text-text-accent` from the parent `<div>` via `currentColor`; `truncate` on the inner span protects long slugs from overflowing the first column.)

- [ ] **Step 3: Typecheck + tests**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm run typecheck && npx vitest run
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/src/components/DiffTable.tsx
git commit -m "feat(web): provider icons in DiffTable (Snapshots)"
```

---

## Task 9: Integrate into `Providers` config page

**Files:**
- Modify: `web/src/pages/Providers.tsx` (header grid ~line 107, row grid ~line 131)

Adds a 20px icon column between the toggle (60px) and the name/description block (1.3fr). The grid template changes on both the header row and each data row to keep columns aligned.

- [ ] **Step 1: Import `ProviderIcon`**

Edit `web/src/pages/Providers.tsx`. Add to the imports:

```tsx
import { ProviderIcon } from "@/components/ProviderIcon";
```

- [ ] **Step 2: Update the header grid**

Replace line 107:

```tsx
        <div className="grid grid-cols-[60px_1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 text-[9.5px] uppercase tracking-widest text-text-muted border-b border-border">
          <div>enabled</div>
          <div>name</div>
          <div>risk</div>
          <div>platforms</div>
          <div>available</div>
          <div>required binary</div>
        </div>
```

with:

```tsx
        <div className="grid grid-cols-[60px_20px_1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 text-[9.5px] uppercase tracking-widest text-text-muted border-b border-border">
          <div>enabled</div>
          <div aria-hidden="true" />
          <div>name</div>
          <div>risk</div>
          <div>platforms</div>
          <div>available</div>
          <div>required binary</div>
        </div>
```

- [ ] **Step 3: Update each provider row**

Replace the existing row container at line 131 (`className="grid grid-cols-[60px_1.3fr_...`) and the block immediately inside it. Find the start of the row (`<div key={p.name} className="grid grid-cols-[...] gap-3 px-3 py-2 items-center ...">`) and change the grid template:

```tsx
              <div
                key={p.name}
                className="grid grid-cols-[60px_20px_1.3fr_0.8fr_1fr_0.6fr_0.9fr] gap-3 px-3 py-2 items-center border-b border-border-subtle hover:bg-bg-elev-1"
              >
```

Then, immediately AFTER the closing `</button>` of the toggle (roughly line 147) and BEFORE `<div>` containing `<Highlight text={p.name} query={query} />`, insert:

```tsx
                <div className="flex items-center justify-center text-text-muted">
                  <ProviderIcon
                    slug={p.name}
                    size={16}
                    className={on ? "text-text" : "text-text-muted"}
                  />
                </div>
```

The icon color tracks the row's on/off state to match the existing name-styling rule (`on ? "text-text" : "text-text-muted"`).

- [ ] **Step 4: Typecheck + tests**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm run typecheck && npx vitest run
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/src/pages/Providers.tsx
git commit -m "feat(web): provider icons in Providers config page"
```

---

## Task 10: Integrate into `CleanupWizard/ReviewStep`

**Files:**
- Modify: `web/src/components/CleanupWizard/ReviewStep.tsx` (provider heading ~line 25)

- [ ] **Step 1: Import `ProviderIcon`**

Edit `web/src/components/CleanupWizard/ReviewStep.tsx`. Add to the imports:

```tsx
import { ProviderIcon } from "@/components/ProviderIcon";
```

- [ ] **Step 2: Insert the icon before `{e.provider} / {e.label}`**

Replace lines 24-27:

```tsx
                <div>
                  <div className="text-text font-medium text-[12px]">
                    {e.provider} / {e.label}
                  </div>
                  <div className="text-text-muted mt-0.5">{e.path}</div>
                </div>
```

with:

```tsx
                <div>
                  <div className="text-text font-medium text-[12px] flex items-center gap-1">
                    <ProviderIcon slug={e.provider} size={12} className="shrink-0" />
                    <span>
                      {e.provider} / {e.label}
                    </span>
                  </div>
                  <div className="text-text-muted mt-0.5">{e.path}</div>
                </div>
```

- [ ] **Step 3: Typecheck + tests**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm run typecheck && npx vitest run
```

Expected: PASS. (The existing `useCleanupWizard` test hits the wizard state, not `ReviewStep`'s DOM, so no augmentation needed.)

- [ ] **Step 4: Commit**

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git add web/src/components/CleanupWizard/ReviewStep.tsx
git commit -m "feat(web): provider icon in cleanup wizard review"
```

---

## Task 11: Build, visual check, and close out

- [ ] **Step 1: Build the frontend**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm run build
```

Expected: clean build, no TypeScript errors, `dist/assets/*.js` emitted. Bundle-size delta vs. baseline should be under ~15 KB gzipped (≈20 simple-icons × 500 B).

- [ ] **Step 2: Run all tests once more**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npx vitest run
```

Expected: ALL PASS. Capture the final count (should be at least 10 tests in `ProviderIcon.test.tsx` plus the one new assertion in `CacheTable.test.tsx`).

- [ ] **Step 3: Start the dev server and visit every touched page**

Run:
```bash
cd /Users/shamil/projects/github/katagun/diskdoctor/web
npm run dev
```

Visit the four surfaces (start the Python backend separately if needed, or seed with mock data):

1. **Scan page** (`/` or `/scan`) — verify an icon sits left of every `r.provider` slug in both density modes; known brands (docker, firefox, pip, huggingface) render their simple-icons mark; unknown slugs render the placeholder rounded square. Column widths do not shift between resolved/unresolved rows.
2. **Snapshots diff** (`/snapshots`) — same check on the first column.
3. **Providers page** (`/providers`) — the 20px icon column sits between the toggle and name; enabled rows show `text-text`-colored icons, disabled rows `text-text-muted`.
4. **Cleanup wizard** — trigger the wizard from Scan, advance to the review step; each entry card shows a 12px icon before `{provider} / {label}`.

- [ ] **Step 4: Confirm no regressions**

Spot-check that the existing UI still works:
- Sort controls in `CacheTable` still change order.
- Highlight/search in `Providers` still highlights matches inside the name/description cell (icon column is not searchable — correct).
- Cleanup wizard still advances and executes.

- [ ] **Step 5: Final commit (only if touched anything)**

If no code changed in this task, skip. Otherwise:

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git status
# ...stage and commit any last touch-ups
```

---

## Out of scope (confirmed non-goals)

- Backend changes (no icon field in `paths.yaml` or API).
- Icons in `Sidebar.tsx` nav or `TopStats.tsx` aggregates.
- Brand-color rendering or hover-color variants.
- Lazy/dynamic import of icons.
- Phase-D local SVGs in `web/src/assets/provider-icons/` — the folder is created empty when needed; no files land in this plan.

## Rollback

Each task is a single commit. To roll back the whole feature:

```bash
cd /Users/shamil/projects/github/katagun/diskdoctor
git log --oneline | grep -E "(provider icon|ProviderIcon|simple-icons)" | awk '{print $1}'
# then: git revert <each commit> --no-edit   (in reverse order)
```

No data migration, no stored state; rollback is purely a code revert.
