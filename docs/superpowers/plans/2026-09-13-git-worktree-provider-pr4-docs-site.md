# Git Worktree Provider, PR 4: Documentation and Site — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell users about the `git-worktrees` provider now that it ships: a README section and roadmap entry, and a marketing-site worktree section with an honest visualization, a provider chip and updated copy.

**Architecture:** Documentation only; no Python or web-app code changes. The README gains a "Git worktrees" section whose state table is checked against `WorktreeState` in the code. `site/index.html` gains a worktree section built on the existing `split`/`panel`/`gauge-legend` pattern with an inline SVG fan-out coloured by the page's risk tokens, plus a provider chip, hero and providers copy. A throwaway Playwright script verifies light and dark rendering at phone, tablet and desktop widths. Pages deploys the site on merge.

**Tech Stack:** Markdown; static HTML/CSS/SVG; Playwright (Chromium) from `web/node_modules` for verification; uv for the README check.

**Spec:** `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` — this plan implements §9 PR 4 ("README provider list; then #91"). Issue #91 (marketing site) carries the site requirements. Built on PRs 1–3 (#100, #101, #108, #109), base `bbb1e1e`.

## Global Constraints

- The site must not advertise a provider users cannot run: it ships after the PR that registers the provider (#91 "Dependencies"; registered in #109).
- Keep **footprint** and **reclaimable** visibly distinct. Never present footprint as reclaimable. Label figures as measured on one machine; do not present one audit as a typical result. (#91 "Honest-numbers constraint")
- Colour worktrees with the page's existing risk vocabulary (`--reclaim`/`.chip.reclaim`, `--danger`/`.chip.danger`): integrated **and** clean → reclaim; integrated with uncommitted changes → danger; not integrated → danger; broken pointer or unverifiable → danger. There is deliberately no `safe` worktree. (#91)
- The worktree section renders correctly in light and dark and does not overflow on narrow viewports (#59 fixed exactly that class of bug). (#91 "Acceptance")
- Pages deploys via `.github/workflows/pages.yml` on merge to `main` when `site/**` changes. (#91)
- README statements must match the shipped provider: states are the `WorktreeState` label texts; removal is `git worktree remove` without `--force`; git 2.36 is required and merge-tree detection needs git 2.38 (spec §4.4, §5.1, §5.2).
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. PR descriptions end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

## Decisions where the spec is silent

1. **Figures are today's measurement on the maintainer's machine** (2026-09-13, `main` at `bbb1e1e`): 150 worktrees, **53.9 GB footprint** (`du -sk` over every worktree path the provider reported), **9.3 GB provably removable** (the provider's own sizes for the 39 integrated, clean worktrees). #91's earlier figures (~48 GB / 10.7 GB) came from a pre-provider audit and are superseded. The panel says the figures were measured on one machine.
2. **The visualization is illustrative**: six generic worktree names (no real repositories) — two integrated and clean (reclaim), one with uncommitted changes, two not integrated, one broken pointer (all danger). It has a `<title>`/`<desc>` for screen readers.
3. **Placement:** the worktree section follows the memory section with its panel on the left, so panel sides keep alternating (disk panel left, memory panel right, worktrees panel left).
4. **Hero stat:** `10+ cache providers` becomes `60+ providers`. 70 providers are registered today (21 built-in classes, 49 YAML paths); rounding down keeps the claim true as the catalog changes.
5. **Unchanged on purpose:** the hero terminal animation and the disk gauge keep their illustrative figures, so the page's illustrative frame stays internally consistent. ROADMAP only gains a "Recently shipped" entry; its older "Now"/"Next" sections are out of scope.
6. **The Playwright check is not committed.** It lives in this plan and runs from a temporary file, like the manual verification steps it replaces.

## Verified behaviour

Observed while this plan's content was built:

- The check script below passes for light and dark at 375, 768 and 1280 px: no page overflow, 2 reclaim and 4 danger worktrees, the SVG inside its panel, the provider chip present, the reclaim stroke resolving to `rgb(154, 103, 0)` in light and `rgb(227, 179, 65)` in dark, and no console errors.
- At 375 px, `span.cm` and `span.out` inside the install terminal extend past the viewport on `main` as well; they sit in `.tb-body`, which scrolls horizontally, and the page itself does not overflow.
- Every worktree state label ends before its `node_modules` block at 1280 px.

## File Structure

| File | Task | Change | Responsibility |
|---|---|---|---|
| `README.md` | 1 | modify | provider families line; new "Git worktrees" section |
| `ROADMAP.md` | 1 | modify | "Recently shipped" entry |
| `site/index.html` | 2 | modify | worktree section (CSS + SVG), provider chip, hero and providers copy, hero stat |

---

### Task 1: README and roadmap

**Files:**
- Modify: `README.md` (provider families paragraph; new `### Git worktrees` section before `## Web UI`)
- Modify: `ROADMAP.md` (`## Recently shipped`)

**Interfaces:**
- Consumes: `devdoctor.providers._worktree_states.WorktreeState` label values (shipped in #108/#109).
- Produces: nothing code-facing.

- [ ] **Step 1: Run the README check to verify it fails**

Run:

```bash
uv run --extra dev --extra web python - <<'PYCHECK'
import re
from pathlib import Path
from devdoctor.providers._worktree_states import WorktreeState
readme = Path("README.md").read_text()
section = readme.split("### Git worktrees", 1)[1].split("\n## ", 1)[0]
labels = {state.value for state in WorktreeState}
rows = re.findall(r"^\| ([^|]+?) \|", section, flags=re.M)[2:]
named = {part.strip() for row in rows for part in row.split(",")}
covered = {label for label in labels if any(label.startswith(n) or n in label for n in named)}
missing = sorted(labels - covered - {"integrated"})
assert "git worktree remove" in section and "--force" in section, "removal command missing"
assert "2.36" in section and "2.38" in section, "git version floors missing"
assert not missing, f"README does not mention states: {missing}"
print("README git worktrees section covers", len(labels), "states")
PYCHECK
```

Expected: `IndexError: list index out of range` (there is no `### Git worktrees` section yet).

- [ ] **Step 2: Update the README**

Apply this change to `README.md` (for example with `git apply`):

````diff
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -58,9 +58,40 @@ devdoctor providers                  # show registered providers and their avail

 Provider families now cover JavaScript (npm, pnpm, Yarn, Bun, and bounded
 `node_modules` discovery), Python/Conda, Go, Rust/Cargo, .NET/NuGet, Android,
-Xcode/iOS, containers, browsers, desktop applications, and local AI tooling.
-Project discovery is bounded to common code roots or the colon-separated paths
-in `DEVDOCTOR_PROJECT_ROOTS`.
+Xcode/iOS, containers, browsers, desktop applications, local AI tooling, and git
+worktrees. Project discovery is bounded to common code roots or the
+colon-separated paths in `DEVDOCTOR_PROJECT_ROOTS`.
+
+### Git worktrees
+
+Coding agents and `git worktree add` leave full checkouts behind, each with its
+own `node_modules`, virtualenvs and build output. The `git-worktrees` provider
+lists every linked worktree that the repositories under your project roots
+register, wherever it lives on disk, and classifies each one without writing to
+the repository or using the network. It needs git 2.36 or later.
+
+| State | Offered as |
+|---|---|
+| integrated, clean, nothing nested inside | **reclaimable**: `git worktree remove <path>`, never `--force` |
+| integrated, uncommitted changes | advice |
+| contains nested repository | advice |
+| not integrated | advice |
+| locked, broken pointer, no default branch, git error, unverifiable | advice |
+
+*Integrated* means merging the worktree's HEAD into the default branch
+(`origin/HEAD`, then `origin/main`, then `origin/master`) would change nothing.
+`git merge-tree` detects this for squash and rebase merges too on git 2.38 or
+later; older git and partial clones detect only true merges and fast-forwards.
+A worktree holding another repository or worktree, even under an ignored path,
+is never offered, because `git worktree remove` would delete it. The contents of
+a removable worktree are counted once, under the worktree, instead of again by
+their own providers. Git re-checks the worktree when cleanup runs, so one that
+changed after the scan is refused.
+
+```bash
+devdoctor scan --provider git-worktrees
+devdoctor clean --execute --provider git-worktrees
+```

 ## Web UI

````

- [ ] **Step 3: Add the roadmap entry**

Apply this change to `ROADMAP.md` (for example with `git apply`):

```diff
diff --git a/ROADMAP.md b/ROADMAP.md
--- a/ROADMAP.md
+++ b/ROADMAP.md
@@ -6,6 +6,11 @@ living backlog lives in [GitHub Issues](https://github.com/katagun/devdoctor/iss

 ## Recently shipped

+- **Git worktrees** — a `git-worktrees` provider finds the worktrees that agents
+  and `git worktree add` leave behind, proves which are integrated into the
+  default branch and clean (squash and rebase merges included), and offers only
+  those for `git worktree remove`. Their contents are counted once, under the
+  worktree. ([#79](https://github.com/katagun/devdoctor/issues/79))
 - **Public launch** — renamed to `devdoctor`, MIT-licensed, a public
   [landing page](https://sysaidmin.com/), and community docs
   (CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue/PR templates).
```

- [ ] **Step 4: Run the README check to verify it passes**

Run the Step 1 command again.
Expected: `README git worktrees section covers 9 states`.

- [ ] **Step 5: Commit**

```bash
git add README.md ROADMAP.md
git commit -m "docs: describe the git worktrees provider" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Marketing site worktree section (#91)

**Files:**
- Modify: `site/index.html` (CSS after `/* disk gauge */` rules; hero lede and stat; new `<!-- WORKTREES -->` section before `<!-- PROVIDERS -->`; providers heading, lede and a first chip)

**Interfaces:**
- Consumes: the page's CSS custom properties (`--reclaim`, `--danger`, `--border-strong`, `--surface`, `--surface-2`, `--accent`, `--text`, `--text-faint`) and classes (`.section`, `.wrap.split`, `.panel`, `.gauge-legend`, `.eyebrow`, `.lede`, `.chip`, `.provs`, `.prov`).
- Produces: `#worktrees` section with `.fanout svg`, six `.wt.reclaim`/`.wt.danger` groups; a `#providers .prov` whose `.pn` is `Git worktrees`.

- [ ] **Step 1: Write the rendering check**

Write this script to a temporary file (it is not committed):

```bash
CHECK="${TMPDIR:-/tmp}/devdoctor-check-site.cjs"
cat > "$CHECK" <<'JS'
// Usage: node check_site.cjs <path-to-site/index.html> <screenshot-dir>
// Resolves playwright from the repository's web/node_modules.
const path = require("path");
const { chromium } = require(path.resolve(process.env.PLAYWRIGHT_FROM || "web/node_modules/playwright"));

(async () => {
  const page_ = path.resolve(process.argv[2]);
  const shots = path.resolve(process.argv[3]);
  require("fs").mkdirSync(shots, { recursive: true });
  const browser = await chromium.launch();
  let failures = 0;
  for (const colorScheme of ["light", "dark"]) {
    for (const width of [375, 768, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      page.on("console", (m) => { if (m.type() === "error" && !/fonts\.g(oogleapis|static)\.com/.test(m.text())) errors.push(m.text()); });
      await page.goto("file://" + page_, { waitUntil: "load" });
      const r = await page.evaluate(() => {
        const doc = document.documentElement;
        const section = document.getElementById("worktrees");
        const svg = section && section.querySelector(".fanout svg");
        const panel = section && section.querySelector(".panel");
        const chip = [...document.querySelectorAll("#providers .prov .pn")].some((n) => n.textContent === "Git worktrees");
        const overflowing = [...document.querySelectorAll("body *")]
          .filter((el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.right > window.innerWidth + 1; })
          .map((el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + (el.className && typeof el.className === "string" ? "." + el.className.split(" ")[0] : ""))
          .slice(0, 5);
        return {
          pageOverflow: doc.scrollWidth - window.innerWidth,
          overflowing,
          hasSection: !!section,
          reclaim: section ? section.querySelectorAll(".wt.reclaim").length : 0,
          danger: section ? section.querySelectorAll(".wt.danger").length : 0,
          svgFits: !!(svg && panel && svg.getBoundingClientRect().right <= panel.getBoundingClientRect().right + 0.5),
          footprintPlaceholder: document.body.innerHTML.includes("__FOOTPRINT__"),
          chip,
          heroStat: [...document.querySelectorAll(".hero-meta .m")].map((m) => m.textContent.trim()),
          stroke: svg ? getComputedStyle(section.querySelector(".wt.reclaim .box")).stroke : null,
        };
      });
      const ok = r.pageOverflow <= 0 && r.hasSection && r.reclaim === 2 && r.danger === 4 && r.svgFits && !r.footprintPlaceholder && r.chip && errors.length === 0;
      if (!ok) failures++;
      console.log(`${ok ? "PASS" : "FAIL"} ${colorScheme} ${width}px overflow=${r.pageOverflow} reclaim=${r.reclaim} danger=${r.danger} svgFits=${r.svgFits} placeholder=${r.footprintPlaceholder} chip=${r.chip} stroke=${r.stroke} errors=${errors.length}${r.overflowing.length ? " overflowing=" + r.overflowing.join(",") : ""}`);
      await page.locator("#worktrees").screenshot({ path: path.join(shots, `worktrees-${colorScheme}-${width}.png`) });
      await context.close();
    }
  }
  await browser.close();
  process.exit(failures ? 1 : 0);
})();
JS
```

Playwright resolves from `web/node_modules`; if that directory is missing, run `cd web && bun ci` first. Chromium must be installed for the Playwright version in `web/` (`cd web && bunx playwright install chromium` if the launch fails).

- [ ] **Step 2: Run the check to verify it fails**

Run: `node "$CHECK" site/index.html "${TMPDIR:-/tmp}/devdoctor-site-shots"` from the repository root.
Expected: the first line is `FAIL light 375px overflow=0 reclaim=0 danger=0 svgFits=false ... chip=false ...`, then the screenshot call throws because `#worktrees` does not exist yet, and the script exits 1.

- [ ] **Step 3: Add the worktree section, chip and copy**

Apply this change to `site/index.html` (for example with `git apply`):

```diff
diff --git a/site/index.html b/site/index.html
--- a/site/index.html
+++ b/site/index.html
@@ -236,6 +236,23 @@ a{color:inherit;text-decoration:none}
 .gauge-legend .sw{width:.7rem;height:.7rem;border-radius:3px;flex:none}
 .gauge-legend b{color:var(--text);font-family:"JetBrains Mono",monospace;margin-left:auto}

+/* worktree fan-out */
+.fanout svg{width:100%;height:auto;display:block}
+.fanout .edge{fill:none;stroke:var(--border-strong);stroke-width:1.4}
+.fanout .edge.reclaim{stroke:var(--reclaim)}
+.fanout .repo{fill:var(--surface-2);stroke:var(--accent);stroke-width:1.5}
+.fanout .repo-name{font:700 13px "JetBrains Mono",monospace;fill:var(--text)}
+.fanout .repo-ref{font:500 9.5px "JetBrains Mono",monospace;fill:var(--text-faint)}
+.fanout .box{stroke-width:1.4}
+.fanout .wt.reclaim .box{stroke:var(--reclaim);fill:color-mix(in srgb,var(--reclaim) 10%,var(--surface))}
+.fanout .wt.danger .box{stroke:var(--danger);fill:color-mix(in srgb,var(--danger) 8%,var(--surface))}
+.fanout .wt-name{font:500 10.5px "JetBrains Mono",monospace;fill:var(--text)}
+.fanout .wt-state{font:500 9px "JetBrains Mono",monospace}
+.fanout .wt.reclaim .wt-state{fill:var(--reclaim)}
+.fanout .wt.danger .wt-state{fill:var(--danger)}
+.fanout .nm{fill:var(--surface-2);stroke:var(--border-strong);stroke-width:1}
+.fanout .nm-text{font:500 8px "JetBrains Mono",monospace;fill:var(--text-faint)}
+
 /* memory meter */
 .meter{margin-top:.4rem}
 .meter-top{display:flex;justify-content:space-between;align-items:baseline;font-size:.82rem;color:var(--text-dim);margin-bottom:.5rem}
@@ -352,7 +369,7 @@ a{color:inherit;text-decoration:none}
     <div class="hero-copy">
       <span class="eyebrow">Local dev-machine diagnostics</span>
       <h1>Your dev machine is hoarding caches it <span class="tint">never told you about.</span></h1>
-      <p class="lede">DevDoctor scans the caches, model weights, containers, and virtualenvs quietly eating your disk — then cleans them up on your terms. Diagnosis first. Nothing deleted until you say so.</p>
+      <p class="lede">DevDoctor scans the caches, model weights, containers, virtualenvs, and leftover git worktrees quietly eating your disk — then cleans them up on your terms. Diagnosis first. Nothing deleted until you say so.</p>
       <div class="hero-actions">
         <div class="cmd">
           <code><span class="pr">$ </span>uv tool install git+https://github.com/katagun/devdoctor</code>
@@ -365,7 +382,7 @@ a{color:inherit;text-decoration:none}
       </div>
       <div class="hero-meta">
         <div class="m"><b>2</b><span>disk &amp; memory, one tool</span></div>
-        <div class="m"><b>10+</b><span>cache providers</span></div>
+        <div class="m"><b>60+</b><span>providers</span></div>
         <div class="m"><b>0</b><span>bytes leave your machine</span></div>
       </div>
     </div>
@@ -488,15 +505,95 @@ a{color:inherit;text-decoration:none}
   </div>
 </section>

+<!-- WORKTREES -->
+<section class="section" id="worktrees" style="padding-top:0">
+  <div class="wrap split">
+    <div class="panel">
+      <div class="fanout">
+        <svg viewBox="0 0 420 260" role="img" aria-labelledby="fanoutTitle fanoutDesc">
+          <title id="fanoutTitle">One repository fanned out into six git worktrees</title>
+          <desc id="fanoutDesc">Each worktree carries its own node_modules. Two are integrated into the default branch and clean, marked reclaimable. Four are marked dangerous: one integrated with uncommitted changes, two not integrated, and one with a broken pointer.</desc>
+          <rect class="repo" x="14" y="110" width="112" height="40" rx="8"/>
+          <text class="repo-name" x="28" y="128">app</text>
+          <text class="repo-ref" x="28" y="142">origin/main</text>
+          <path class="edge reclaim" d="M126 130C162 130 160 25 196 25"/>
+          <g class="wt reclaim">
+            <rect class="box" x="196" y="8" width="216" height="34" rx="7"/>
+            <text class="wt-name" x="206" y="22">wt/fix-login</text>
+            <text class="wt-state" x="206" y="35">integrated · clean</text>
+            <rect class="nm" x="334" y="16" width="70" height="18" rx="4"/>
+            <text class="nm-text" x="369" y="28" text-anchor="middle">node_modules</text>
+          </g>
+          <path class="edge reclaim" d="M126 130C162 130 160 67 196 67"/>
+          <g class="wt reclaim">
+            <rect class="box" x="196" y="50" width="216" height="34" rx="7"/>
+            <text class="wt-name" x="206" y="64">wt/pr-327</text>
+            <text class="wt-state" x="206" y="77">integrated · clean</text>
+            <rect class="nm" x="334" y="58" width="70" height="18" rx="4"/>
+            <text class="nm-text" x="369" y="70" text-anchor="middle">node_modules</text>
+          </g>
+          <path class="edge" d="M126 130C162 130 160 109 196 109"/>
+          <g class="wt danger">
+            <rect class="box" x="196" y="92" width="216" height="34" rx="7"/>
+            <text class="wt-name" x="206" y="106">wt/agent-refactor</text>
+            <text class="wt-state" x="206" y="119">uncommitted changes</text>
+            <rect class="nm" x="334" y="100" width="70" height="18" rx="4"/>
+            <text class="nm-text" x="369" y="112" text-anchor="middle">node_modules</text>
+          </g>
+          <path class="edge" d="M126 130C162 130 160 151 196 151"/>
+          <g class="wt danger">
+            <rect class="box" x="196" y="134" width="216" height="34" rx="7"/>
+            <text class="wt-name" x="206" y="148">wt/spike-cache</text>
+            <text class="wt-state" x="206" y="161">not integrated</text>
+            <rect class="nm" x="334" y="142" width="70" height="18" rx="4"/>
+            <text class="nm-text" x="369" y="154" text-anchor="middle">node_modules</text>
+          </g>
+          <path class="edge" d="M126 130C162 130 160 193 196 193"/>
+          <g class="wt danger">
+            <rect class="box" x="196" y="176" width="216" height="34" rx="7"/>
+            <text class="wt-name" x="206" y="190">wt/codex-search</text>
+            <text class="wt-state" x="206" y="203">not integrated</text>
+            <rect class="nm" x="334" y="184" width="70" height="18" rx="4"/>
+            <text class="nm-text" x="369" y="196" text-anchor="middle">node_modules</text>
+          </g>
+          <path class="edge" d="M126 130C162 130 160 235 196 235"/>
+          <g class="wt danger">
+            <rect class="box" x="196" y="218" width="216" height="34" rx="7"/>
+            <text class="wt-name" x="206" y="232">wt/old-checkout</text>
+            <text class="wt-state" x="206" y="245">broken pointer</text>
+            <rect class="nm" x="334" y="226" width="70" height="18" rx="4"/>
+            <text class="nm-text" x="369" y="238" text-anchor="middle">node_modules</text>
+          </g>
+        </svg>
+      </div>
+      <div class="gauge-legend" style="margin-top:1.2rem">
+        <div class="li"><span class="sw" style="background:var(--border-strong)"></span>Worktree footprint <b>53.9 GB</b></div>
+        <div class="li"><span class="sw" style="background:var(--reclaim)"></span>Provably removable <b>9.3 GB</b></div>
+      </div>
+      <p class="lede" style="margin-top:1rem;font-size:.86rem">Measured on one developer's machine: 150 worktrees, 39 of them integrated and clean. Yours will differ, and footprint is never counted as reclaimable.</p>
+    </div>
+    <div>
+      <span class="eyebrow">Agent exhaust, verified</span>
+      <h2 class="head" style="font-size:clamp(1.6rem,3vw,2.2rem);margin-top:1rem">Merged is not the same as safe to delete.</h2>
+      <p class="lede" style="margin-top:1rem">Coding agents check out a fresh git worktree for every task, and each one carries its own <code class="mono" style="font-size:.86em">node_modules</code>, virtualenv and build output. DevDoctor finds every worktree your repositories register and proves which ones can go: integrated into the default branch, squash and rebase merges included, with no uncommitted changes and nothing nested inside. Only those are offered, through <code class="mono" style="font-size:.86em">git&nbsp;worktree&nbsp;remove</code> and never <code class="mono" style="font-size:.86em">--force</code>. Everything else stays advice.</p>
+      <div class="provs" style="margin-top:1.6rem">
+        <span class="chip reclaim">integrated &amp; clean — removable</span>
+        <span class="chip danger">unmerged, uncommitted or broken — advice only</span>
+      </div>
+    </div>
+  </div>
+</section>
+
 <!-- PROVIDERS -->
 <section class="section" id="providers" style="padding-top:0">
   <div class="wrap">
     <div class="head">
       <span class="eyebrow">Knows where the bloat hides</span>
-      <h2>Built for the caches modern dev work leaves behind.</h2>
-      <p class="lede">Especially AI/ML work — model weights are the new disk sink. DevDoctor ships with providers for the usual offenders, plus a YAML-driven list you can extend for anything else.</p>
+      <h2>Built for what modern dev work, and your agents, leave behind.</h2>
+      <p class="lede">Especially AI-assisted work: model weights and agent worktrees are the new disk sinks. DevDoctor ships with providers for the usual offenders, plus a YAML-driven list you can extend for anything else.</p>
     </div>
     <div class="provs">
+      <span class="prov"><svg class="pi" viewBox="0 0 24 24" fill="none"><circle cx="6" cy="5" r="2" stroke="currentColor" stroke-width="1.4"/><circle cx="6" cy="19" r="2" stroke="currentColor" stroke-width="1.4"/><circle cx="18" cy="8" r="2" stroke="currentColor" stroke-width="1.4"/><path d="M6 7v10M18 10c0 4-6 3-10 7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg><span><span class="pn">Git worktrees</span> <span class="ps">agent scratch space</span></span></span>
       <span class="prov"><svg class="pi" viewBox="0 0 24 24" fill="none"><rect x="3" y="10" width="4" height="4" stroke="currentColor" stroke-width="1.4"/><rect x="8" y="10" width="4" height="4" stroke="currentColor" stroke-width="1.4"/><rect x="13" y="10" width="4" height="4" stroke="currentColor" stroke-width="1.4"/><rect x="8" y="5.5" width="4" height="4" stroke="currentColor" stroke-width="1.4"/><path d="M18 12c2 0 3-1 3-1s0 4-4 5c-1.5 2-4 3-7 3-5 0-8-3-8-7h16Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg><span><span class="pn">Docker</span> <span class="ps">images · volumes · build cache</span></span></span>
       <span class="prov"><svg class="pi" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.4"/><circle cx="9" cy="10" r="1.3" fill="currentColor"/><circle cx="15" cy="10" r="1.3" fill="currentColor"/><path d="M8.5 15c1 1 5 1 7 0" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg><span><span class="pn">Hugging Face</span> <span class="ps">~/.cache/huggingface</span></span></span>
       <span class="prov"><svg class="pi" viewBox="0 0 24 24" fill="none"><path d="M12 3c3 0 5 2 5 5 2 1 3 3 3 5 0 4-4 8-8 8s-8-4-8-8c0-2 1-4 3-5 0-3 2-5 5-5Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg><span><span class="pn">Ollama</span> <span class="ps">local model store</span></span></span>
```

- [ ] **Step 4: Run the check to verify it passes**

Run: `node "$CHECK" site/index.html "${TMPDIR:-/tmp}/devdoctor-site-shots"`
Expected: six `PASS` lines (light and dark × 375, 768, 1280 px) and exit code 0. `overflowing=span.cm,span.out` on the 375 px lines is expected: those spans are inside the horizontally scrolling install terminal and are reported on `main` too.

- [ ] **Step 5: Look at the screenshots**

Open `worktrees-light-375.png`, `worktrees-dark-1280.png` and one more from the screenshot directory. Check: branch colours match the chips (amber reclaim, red danger); no state label overlaps its `node_modules` block; footprint and "Provably removable" are separate rows; the copy reads cleanly in both themes.

- [ ] **Step 6: Commit**

```bash
git add site/index.html
git commit -m "feat(site): show git worktrees on the landing page" -m "Closes #91." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Verify, open the PR, merge, confirm the deploy

**Files:** none.

- [ ] **Step 1: Re-run both checks on the final tree**

Run the Task 1 README check and the Task 2 site check.
Expected: `README git worktrees section covers 9 states`; six `PASS` lines.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin docs/git-worktree-provider
gh pr create --base main --title "docs: git worktrees in the README, roadmap and landing page" --body "$(cat <<'EOF'
PR 4 of 4 for #79, per the design spec (docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §9). Documentation and site only.

## What

- README: git worktrees in the provider families, and a "Git worktrees" section with the classification table, what *integrated* means (git 2.38+ for squash and rebase merges), the nested-repository rule, and example commands.
- ROADMAP: "Recently shipped" entry for #79.
- Landing page (#91):
  - a worktree section with an inline SVG fan-out coloured by the page's risk vocabulary (integrated and clean → reclaim; everything else → danger, no safe branch);
  - footprint and provably removable figures shown separately and labelled as measured on one machine (150 worktrees, 53.9 GB footprint, 9.3 GB provably removable);
  - a "Git worktrees · agent scratch space" provider chip, hero and providers copy, and `60+ providers` in the hero stats.

## Verification

- A README check asserts the state table covers every `WorktreeState` label and names the removal command and git version floors.
- A Playwright check passes in light and dark at 375, 768 and 1280 px: no page overflow, six worktree nodes with the right risk classes, and no console errors.

Closes #91.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge once the required checks pass**

The required checks are `Python (lint, types, tests)` and `Web (typecheck, tests, build)`. Also read any CodeQL annotations. When everything passes:

```bash
gh pr merge --squash --delete-branch
```

If `--delete-branch` cannot delete the remote branch because `main` is checked out in another worktree, delete it after confirming the PR is merged: `git push origin :refs/heads/docs/git-worktree-provider`.

- [ ] **Step 4: Confirm the Pages deploy and the live page**

```bash
gh run list --workflow pages.yml --limit 1
curl -fsSL https://sysaidmin.com/ | grep -c "Git worktrees"
```

Expected: the latest `Deploy landing page to GitHub Pages` run for the merge commit concludes `success`, and the live page contains `Git worktrees` (count ≥ 1). Pages can take a minute to publish after the run.
