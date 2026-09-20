# Docs for agents

Driving DevDoctor from an LLM or coding agent? This page is the contract.
(It mirrors `.claude/skills/devdoctor/SKILL.md` in this repo, published here
so agents outside this checkout can use it too.)

## Capabilities

- `devdoctor scan --json` — **read-only**. Never deletes, moves, or modifies
  anything. Safe to run on any schedule, unsupervised.
- `devdoctor providers` — registered providers and availability. Check this
  before assuming a provider exists on the machine.
- `devdoctor recipe` — emits a fully commented-out cleanup script. The safe
  way to propose a cleanup for a human to review.
- `devdoctor clean` (no flags) — preview only. Zero prompts, zero shell
  calls. Safe to run to show the human what *would* happen.
- `devdoctor clean --execute` — **destructive**. Requires a human decision
  (see rules below). Never run unsupervised.
- `devdoctor serve` — local web UI on loopback. Do not expose it; do not
  firewall-punch it; it has no auth because it never leaves the machine.

## Rules for `clean --execute`

1. **Confirm intent first.** Only run `--execute` when the user explicitly
   asked to reclaim space / delete caches. A scan report is not consent.
2. **Preview or recipe first.** Show `clean` (preview) or the `recipe`
   script before executing, unless the user already approved a plan.
3. **Stay at or below the approved tier.** `--risk safe` with `--yes-safe`
   for routine runs. Reclaimable entries need per-entry approval —
   surface them one by one, do not pre-answer. `--allow-dangerous` only
   with explicit user say-so, never by default, never bundled into a
   routine command.
4. **Scope when you can.** `--provider <name>` narrows a run to what was
   discussed (e.g. `--provider docker`).
5. **No terminal means `--yes` or nothing.** `--execute` refuses without
   `--yes` when stdin is not a terminal. Do not add `--yes` to dodge a
   missing human — unattended `--execute` needs prior explicit approval.
6. **Report the summary.** Estimated reclaimed vs. planned, measured
   free-space change, and any APFS-snapshot caveat. If free space lags,
   check `time-machine-local-snapshots` (macOS) before declaring success.

## Reading `scan --json`

- Headline: `total_reclaimable_bytes`. Breakdown: `per_provider` (biggest
  first). Detail: `entries[]` with `provider`, `label`, `path`,
  `size_bytes`, `risk`, `actions`.
- Sizes are estimates: `footprint_bytes` (allocated),
  `reclaimable_bytes` (expected freeing), `shared_bytes` (hard-linked,
  counted once). Do not present estimates as measured freed bytes.
- `diagnostics` lists unreadable paths and unavailable providers — mention
  them so the human knows what the total excludes.
- The Rich table truncates when captured: always parse `--json`, never the
  human table.
- `path` may be `null` (non-path entries like snapshots). `risk` is one of
  `safe` / `reclaimable` / `dangerous`.

## Safety model in one paragraph

Preview by default; the plan prints before anything runs; risk tiers gate
execution (safe auto-approvable, reclaimable always prompted, dangerous
skipped unless `--allow-dangerous`); cleanup actions are typed deletions or
argv commands, never shell strings; every run is recorded in the shared
history log. Full version: [Safety model](safety-model.md).
