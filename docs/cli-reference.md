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
devdoctor scan --provider docker     # run only these providers
devdoctor scan --older-than 6mo      # only entries untouched for that long
devdoctor scan --sort age            # longest untouched first (default: size)
devdoctor scan --coverage            # also list what no provider accounts for
```

`--risk` accepts `safe`, `reclaimable`, `dangerous`, repeatable or
comma-separated.

`--provider` is repeatable or comma-separated and decides what runs: the other
providers are never started, so a scoped scan takes as long as its providers
do. An unknown name is an error; `devdoctor providers` lists them.

`--older-than` takes whole hours, days, weeks, months (30 days) or years:
`12h`, `90d`, `2w`, `6mo`, `1y`. Age is the newest modification of anything inside
the entry, not of the directory itself, whose own timestamp does not move when
a file deep inside changes. For a git worktree it is the last commit on its
branch; for the Time Machine bundle, the youngest snapshot it deletes. Entries whose age is unknown are
left out, because "old enough" has to be shown, not assumed. The table's `Age`
column shows the same figure.

Every unfiltered scan ends with a coverage line: how much of the used space on
the volume holding your home directory the scan accounts for. A scan reports
what its providers know about, which is rarely most of the disk, and the line
says so instead of letting the total read as "that is all there is".
`--coverage` goes further: it sizes the home directory outside every classified
path and lists the ten largest directories no provider accounts for, three
levels deep. It walks what the scan did not, so expect it to take longer than
the scan itself. It needs an unfiltered scan. Paths macOS will not let the
terminal read are counted and reported, not guessed at.

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
| `coverage` | `used_bytes`, `classified_bytes`, `ratio`; with `--coverage` also `unclassified` (`path`, `bytes`, `files_only`) and `skipped`. `null` on a filtered scan |

Each entry carries `provider`, `id`, `path` (may be `null`), `label`,
`size_bytes`, `footprint_bytes`, `reclaimable_bytes`, `shared_bytes`,
`apparent_bytes` (the files' summed lengths where measured, else `null`; far
above the footprint for a sparse VM disk image, and never reclaimable),
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
| `--provider` | Run only these providers (repeatable or comma-separated). |
| `--older-than` | Include only entries untouched for at least this long (`12h`, `90d`, `2w`, `6mo`, `1y`). |
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
