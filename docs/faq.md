# FAQ

## Why did my free space not change after a cleanup?

The three usual causes, in order of likelihood on macOS:

1. **Time Machine local snapshots pin the freed blocks.** Hourly snapshots
   keep deleted data allocated until they age out. Thin them (keeping the
   newest restore point) and the space appears:
   ```bash
   devdoctor scan --provider time-machine-local-snapshots
   devdoctor clean --execute --provider time-machine-local-snapshots
   ```
   The end-of-run summary says so explicitly when it detects the measured
   change lagging the estimate for this reason.
2. **Docker Desktop compacts its VM disk later.** A prune frees space
   *inside* the VM; the `Docker.raw` file on your Mac shrinks afterwards,
   not instantly. Judge the prune with `docker system df`, then give it time
   or force it with
   `docker run --privileged --pid=host docker/desktop-reclaim-space`. Docker
   may stop answering for a few minutes while it compacts. Deleting files
   inside a running container frees nothing on the host; only removing images,
   containers, volumes or build cache does.
3. **You cleaned advice-only entries.** Entries marked `·` in the run output
   print guidance instead of running anything — re-read the summary's
   estimated-vs-planned numbers.

On Linux, cause 1 does not apply (no Time Machine provider); check 2 and 3.

## How does DevDoctor measure space?

Three distinct numbers, kept separate on purpose:

- **Footprint** — storage actually allocated on disk.
- **Estimated reclaimable** — what cleanup is expected to free. An estimate,
  not a promise.
- **Shared** — allocations hard-linked from multiple places and counted once.

A fourth figure appears only for sparse files: **apparent size**, the file's
length. Docker Desktop's `Docker.raw` is 80 GB long by default and occupies
only what Docker has written, often less than half. DevDoctor counts what it
occupies, because that is what your disk gives up; Finder and `ls` show the
length. `scan` prints a `Sparse:` note under the table for such an entry, and
`--json` carries `apparent_bytes`. The difference was never on your disk, so
it is described and never offered as reclaimable.

Cleanup results remain estimates unless a provider explicitly verifies the
post-clean size. The summary reports estimated reclaimed vs. planned plus
the measured free-space change so you can see all three side by side.

## Why is an entry's size "unknown"?

Some things cannot be measured without doing the destructive thing first
(macOS does not disclose per-snapshot sizes, a cache may need a tool to
enumerate it). DevDoctor offers the entry with unknown size rather than
hiding it — the plan still shows the exact command, and you decide.

## Why is something skipped?

The run output marks every skip with a reason: `dangerous` without
`--allow-dangerous`, advice-only entries, covered entries (a bundle you
approved already handles them), entries that changed after the scan (git
worktrees are re-checked before removal), and entries whose provider
reported them unavailable.

## Why does `uv cache clean` hang or fail when I run DevDoctor with `uv run`?

`uv run` and `uvx` hold the uv cache lock for as long as the program they
started is running, so a `uv cache clean` started from inside waits for that
lock forever. DevDoctor notices when it is running under uv (both export
`UV=<path to uv>` to their child) and passes `--force`; the plan shows the
exact command, and a scan says so in its diagnostics. It is safe: the
running environment keeps its own copies of its packages. A `devdoctor`
installed with `uv tool install` runs on its own and needs no override.

## Do I need Full Disk Access / sudo?

Only for seeing everything. Unreadable paths land in the report's
`diagnostics` and are excluded from totals. If the total looks too small
for your disk, grant Full Disk Access (System Settings › Privacy &
Security) on macOS or re-run with elevated privileges, then compare.

## Is my data sent anywhere?

No. Scanning, cleanup, and the web UI are all local; the landing page ships
no cookies or analytics. The only network calls DevDoctor itself makes are
the ones your package tools would make anyway when re-downloading.

## Where do snapshots and history live?

Snapshots (`devdoctor snapshot` / `diff`) and the cleanup history log
(`devdoctor history`) share one local store used by both the CLI and the
web UI — record in one surface, read back in the other.
