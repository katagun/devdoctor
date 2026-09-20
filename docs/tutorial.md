# Reclaim disk space with DevDoctor — an end-to-end tutorial

This tutorial walks a full cleanup pass: scan, read the report, handle the
two big "why didn't my free space change?" traps (Docker's VM disk and Time
Machine local snapshots), preview a cleanup, then run the safe tier. It is
written from a real session on a Mac that went from **14 GB to 70 GB free**.

Assumes DevDoctor is installed (`uv tool install --from
git+https://github.com/katagun/devdoctor devdoctor`). Every step is
repeatable — nothing below deletes anything until step 6.

## 1. Scan and read the report

```bash
devdoctor scan --json > /tmp/dd_report.json
```

`scan` is read-only: it never deletes, moves, or modifies anything. `--json`
emits the structured report (see [CLI reference](cli-reference.md) for the
full contract). Summarize it:

- `total_reclaimable_bytes` — the headline: estimated reclaimable space.
- `per_provider` — bytes per provider, biggest first. This tells you *where*
  to look.
- `entries` — one item per cleanable thing, each with `provider`, `label`,
  `path`, `size_bytes`, `risk` (`safe` / `reclaimable` / `dangerous`), and
  the `actions` DevDoctor would take.
- `diagnostics` — paths that could not be read (e.g. permission denied).
  Entries you cannot see cannot be counted; re-run with Full Disk Access or
  `sudo` if the total looks too small.

Prefer `--json` whenever output is piped or captured: the Rich table that
`devdoctor scan` prints to a terminal truncates wide rows.

To scope a scan while exploring, filter by size, risk, or provider:

```bash
devdoctor scan --min-size 100M --risk safe,reclaimable
devdoctor scan --provider docker
devdoctor providers   # everything registered, with availability
```

## 2. Understand the risk tiers before touching anything

Every entry carries one risk label, and the label decides what cleanup is
allowed to do with it:

| Risk | Meaning | `clean` behavior |
|---|---|---|
| `safe` | Regenerable caches (package-manager downloads, build caches) | Offered; `--yes-safe` auto-approves |
| `reclaimable` | Rebuildable but costs time/bandwidth (containers, models, worktrees) | Offered; always prompted per entry |
| `dangerous` | May hold durable user data (`~/Downloads`, named Docker volumes, large files) | **Skipped** unless `--allow-dangerous` |

Dangerous entries are usually advice-only: DevDoctor prints what *you* could
do instead of running anything. See [Safety model](safety-model.md) and the
[provider catalogue](providers.md) for per-provider levels.

## 3. Docker: prune inside the VM, expect the host file to lag

On Docker Desktop (macOS), containers and images live inside a Linux VM whose
disk is a file on your Mac (`Docker.raw`). DevDoctor's `docker` provider
prunes *inside* the VM (`docker system prune`, unused volumes reviewed one by
one — named volumes are dangerous, anonymous ones reclaimable).

The trap: after a big prune, Finder's free space may barely move. The VM disk
file compacts **later**, not instantly. Give it time, restart Docker Desktop
if you are in a hurry, and judge the prune by `docker system df`, not by the
menu-bar number in the first minute. This is the same class of surprise as
the next section — see [FAQ: free space didn't change](faq.md).

## 4. Time Machine: thin the local snapshots that pin freed blocks

On macOS, hourly Time Machine local snapshots pin disk blocks: other
cleanups can delete files yet the space stays allocated until the snapshots
age out. If a cleanup reports success but free space is flat, check here
first:

```bash
devdoctor scan --provider time-machine-local-snapshots
```

The provider lists each snapshot plus one bundle entry that deletes **all
but the newest** restore point (newest first), so you always keep a restore
point. macOS system-update snapshots (`com.apple.os.update-*`) are never
touched, and deleting local snapshots never touches the external backup
drive. In the session this tutorial is based on, thinning snapshots was the
step that finally released the space other cleanups had already freed.

(Linux has no equivalent provider — skip this step there.)

## 5. Preview the cleanup — still nothing deleted

```bash
devdoctor clean
```

`clean` with no flags prints the same report table as `scan` and stops.
Zero prompts, zero shell calls. For a reviewable artifact instead, emit the
commented-out script and read it before uncommenting anything:

```bash
devdoctor recipe -o /tmp/cleanup.sh   # everything commented out; you pick
```

## 6. Run the safe tier, then decide about the rest

```bash
devdoctor clean --execute --yes-safe
```

What happens, in order:

1. The **plan prints first** — every entry with path, risk, estimated
   reclaim, and the exact command.
2. You confirm once; then each entry runs with a per-entry line (`✓` done,
   `✗` failed with the command's error, `-` skipped, `·` advice-only).
3. The **summary** states estimated reclaimed vs. planned plus the measured
   free-space change. Sizes are estimates — DevDoctor does not measure freed
   bytes — and on macOS it says so explicitly when APFS snapshots hold the
   measured change down (see step 4).
4. Every run is recorded. `devdoctor history` lists runs; `devdoctor
   history 1` replays the newest entry by entry.

`--yes-safe` auto-approves only `safe` entries; everything reclaimable is
still prompted. Worked example from the real session:

```bash
devdoctor clean --execute --risk safe --provider uv-cache   # one safe cache
devdoctor clean --execute --yes-safe                        # all safe entries
devdoctor clean --execute --provider docker                 # reclaimable, prompted
devdoctor clean --execute --provider time-machine-local-snapshots
```

Unattended runs add `--yes` (plan still prints, final confirmation skipped);
without a terminal, `--execute` refuses to run unless `--yes` is passed.
`--allow-dangerous` is intentionally a separate, explicit opt-in — never
combine it into a routine command.

## 7. Prove it with snapshots, or click through it instead

Before/after evidence:

```bash
devdoctor snapshot --note "before cleanup"
# ... clean ...
devdoctor diff --to live   # last snapshot vs. now
```

Prefer a GUI? `devdoctor serve` (needs the `web` extra) opens the local
dashboard with the same engine: Disk and Memory pages, a step-by-step
cleanup wizard with live output, history, and settings. See [Web UI
guide](web-ui.md).

## Next steps

- [CLI reference](cli-reference.md) — every command and flag.
- [Provider catalogue](providers.md) — what each provider covers and its risk.
- [Safety model](safety-model.md) — the guarantees cleanup runs on.
- [FAQ](faq.md) — "why did my free space not change?", estimates vs.
  measured, permissions.
- Driving DevDoctor from an agent or LLM? Read
  [Docs for agents](agents.md).
