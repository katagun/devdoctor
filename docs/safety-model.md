# Safety model

DevDoctor runs destructive commands, so safety is the design — not a flag.

## The five guarantees

1. **Preview by default.** `clean` without `--execute` prints the report and
   stops: zero prompts, zero shell calls. `scan` never modifies anything.
2. **The plan prints before anything runs.** With `--execute`, every entry is
   shown with its path, risk, estimated reclaim, and the exact command —
   then DevDoctor asks once before starting.
3. **Risk tiers gate execution.** `safe` entries may be auto-approved with
   `--yes-safe`. `reclaimable` entries are always prompted individually.
   `dangerous` entries are **skipped** unless `--allow-dangerous` is passed
   explicitly — and are usually advice-only (an `echo` describing what you
   could do, not an `rm`).
4. **No shell.** Cleanup actions are typed path deletions, argv command
   lists, or non-executable advice. Commands never pass through a shell;
   paths are quoted.
5. **Everything is recorded.** Every run lands in the history log
   (`devdoctor history`), shared by the CLI and the web UI.

## Numbers are honest about being estimates

Disk figures distinguish **footprint** (allocated storage), **estimated
reclaimable** space, and **shared** hard-linked allocations. Cleanup results
stay estimates unless a provider explicitly verifies the post-clean size.
The end-of-run summary compares estimated reclaimed vs. planned alongside
the measured free-space change — and on macOS it says so when APFS local
snapshots hold the measured change down. See the
[FAQ](faq.md#why-did-my-free-space-not-change-after-a-cleanup).

## Edge cases the model already handles

- Unused Docker volumes are reviewed and removed **individually**. Anonymous
  volumes are reclaimable; named volumes are dangerous and stay off by
  default because they may contain durable application data.
- A git worktree holding another repository is never offered, because `git
  worktree remove` would delete it. Removable worktrees are re-checked
  immediately before removal; one that changed after the scan is skipped.
- Covering entries (e.g. the Time Machine all-but-newest bundle) are
  prompted before what they cover; approving the bundle resolves the rest as
  skipped, declining prompts each one individually.
- `recipe` always emits a **fully commented-out** script. Nothing runs until
  you uncomment it.
- Without a terminal, `--execute` refuses to run unless `--yes` is passed —
  unattended runs cannot happen by accident.

## For agents and automation

Scan is read-only and safe to run on any schedule. `clean` needs `--execute`
plus an explicit human decision for anything above `safe`; never pass
`--allow-dangerous` without explicit user say-so. The full agent procedure
lives in [Docs for agents](agents.md).
