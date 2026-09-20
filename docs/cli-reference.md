# CLI reference

The `devdoctor` CLI. Global flag: `-v` / `--verbose` (debug logging to
stderr). All sizes accept suffixes like `100M`, `2G`.

## `devdoctor scan` — read-only inventory

Prints a Rich table of all known caches, sorted by size. Never deletes
anything. Prefer `--json` when piping or capturing (the table truncates).

```bash
devdoctor scan
devdoctor scan --json                # structured Report JSON to stdout
devdoctor scan --min-size 100M       # hide entries below this size
devdoctor scan --risk safe,reclaimable   # include only these risks
devdoctor scan --provider docker     # repeatable; limit to providers
```

`--risk` accepts `safe`, `reclaimable`, `dangerous`, repeatable or
comma-separated.

### `scan --json` contract

Top-level object:

| Key | Meaning |
|---|---|
| `schema_version`, `kind` | Report format version and kind |
| `scanned_at`, `started_at`, `duration_ms` | Timing |
| `hostname`, `platform` | Where the scan ran |
| `note` | Snapshot note, if any |
| `total_bytes`, `total_footprint_bytes`, `total_reclaimable_bytes`, `total_shared_bytes` | Totals (see [FAQ](faq.md#how-does-devdoctor-measure-space) for footprint vs. reclaimable vs. shared) |
| `unknown_reclaimable_entries` | Entries whose reclaim is unknown |
| `entry_count` | Number of entries |
| `per_provider` | Per-provider totals: `name`, `bytes`, `entries`, `duration_ms`, `footprint_bytes`, `reclaimable_bytes`, `shared_bytes` |
| `entries` | One object per entry (omitted for auto snapshots) |
| `diagnostics` | Unreadable paths and provider warnings |

Each entry carries `provider`, `id`, `path` (may be `null`), `label`,
`size_bytes`, `footprint_bytes`, `reclaimable_bytes`, `shared_bytes`,
`risk` (`safe` / `reclaimable` / `dangerous`), `recipe` (shell lines for the
recipe script), `actions` (typed cleanup actions), plus file metadata
(`uid`, `gid`, `mode`, `owner`, `group`, `perms`) and `mtime`.

## `devdoctor clean` — preview by default, act with `--execute`

```bash
devdoctor clean                      # preview: report table, no prompts, no shell calls
devdoctor clean --execute            # plan prints, per-entry prompts, one confirmation, then runs
devdoctor clean --execute --yes-safe # safe entries need no per-entry prompt
devdoctor clean --execute --yes-safe --yes   # unattended: plan still prints, no confirmation
devdoctor clean --execute --risk safe --provider uv-cache   # scope a run
devdoctor clean --execute --allow-dangerous  # include dangerous entries (explicit opt-in)
```

| Flag | Effect |
|---|---|
| `--execute` | Actually run. Without it: preview only. Refuses without `--yes` when stdin is not a terminal. |
| `--yes-safe` | Auto-approve `safe` entries; reclaimable still prompted. |
| `--yes` | Skip the final confirmation (plan still prints). Unattended runs also need `--yes-safe`. |
| `--risk` | Include only these risks (`safe`, `reclaimable`, `dangerous`; repeatable or comma-separated). |
| `--provider` | Limit to these providers (repeatable). |
| `--allow-dangerous` | Offer dangerous entries too; otherwise skipped. Never pass without explicit user say-so. |

During a run each entry prints one line: `✓` done, `✗` failed (with the
command's error), `-` skipped (with reason), `·` advice-only. The summary
gives estimated reclaimed vs. planned and the measured free-space change;
on macOS it calls out APFS snapshots when the measured change lags the
estimate. Covering entries (e.g. the Time Machine all-but-newest bundle)
are prompted before the entries they cover: approving the bundle resolves
the covered entries as skipped without further prompts.

## `devdoctor recipe` — reviewable cleanup script

Emits a shell script with **every line commented out** — review, uncomment
what you want, run it yourself.

```bash
devdoctor recipe                     # all providers, to stdout
devdoctor recipe --provider ollama   # one provider
devdoctor recipe -o /tmp/cleanup.sh  # write to file
```

## `devdoctor snapshot` / `devdoctor diff` — track usage over time

```bash
devdoctor snapshot --note "before cleanup"
devdoctor diff                       # latest two snapshots
devdoctor diff --to live             # last snapshot vs. current disk state
```

The CLI and the web UI share one snapshot store and one history log.

## `devdoctor history` — past cleanup runs

```bash
devdoctor history                    # past runs, newest first
devdoctor history 1                  # the newest run, entry by entry
```

## `devdoctor providers` — what is available here

Lists registered providers and whether each is available on this machine
(missing binaries and wrong platforms are reported, not hidden).

## `devdoctor serve` — local web UI

```bash
devdoctor serve                       # needs the `web` extra; opens a browser tab
devdoctor serve --port 8731 --no-browser
```

`--port N` binds a specific port (`0` = random free port, the default);
`--no-browser` skips auto-opening. See the [Web UI guide](web-ui.md).
