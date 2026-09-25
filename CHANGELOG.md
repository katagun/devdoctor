# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

DevDoctor is pre-1.0 and has not been released or published yet. Everything
built so far is collected under **Unreleased**; the first cut will move these
entries under a versioned heading as described in
[RELEASING.md](RELEASING.md).

## [Unreleased]

### Changed

- **Scans are about 2.4x faster with byte-identical results.** Directory sizing
  was 83% of a scan and ran one tree at a time inside each provider. Trees are
  now walked with one `stat` per entry and no per-file path objects, a few at a
  time on one shared pool of four walks (more made the same trees slower on
  APFS). Reference machine, 503 entries and 168 GB: 160 s to 68 s, with 471 of
  474 comparable entries identical to the byte and the other three changed on
  disk between runs. `scripts/bench_sizer.py` reproduces the comparison, and
  `DEVDOCTOR_SIZER_WORKERS` overrides the pool size. Sizes are still never
  cached between scans: no cheap key proves a cached size is current. (#92)
- **A wedged Docker daemon no longer hangs the scan.** `docker system df` blocks
  for as long as the daemon does; each Docker query is now bounded at 60 s and
  reports a diagnostic instead. (#92)
- **`--provider` decides what runs, not just what is shown.** A scan limited to
  some providers used to run every provider and filter afterwards, so
  `scan --provider time-machine-local-snapshots` took as long as a full scan
  (160 s on the reference machine, now 0.2 s). `scan`, `clean`, `recipe` and the
  web recipe endpoint now run only the named providers, and a web cleanup job
  re-scans only the providers that own the selected entries. Provider names may
  be comma-separated, and an unknown name is a usage error instead of an empty
  result. (#92)
- **`devdoctor clean --execute` shows what it will do before it does it.** The
  itemized plan (path, risk, estimated reclaim, exact command) prints before
  the single confirmation whatever the flags; each entry prints a line as it
  finishes, with the command's error when it fails; the summary states
  estimated reclaimed versus planned and the measured free-space change, in
  human units. The scan phase names the running providers. (#126)
- **Project scans follow a marker-anchored depth budget instead of a flat cap.**
  Both project-walking providers measured depth from the scan root and stopped at
  six levels, which a normal monorepo inside a worktree exhausts immediately
  (`~/projects/github/org/repo/.worktrees/branch/apps/web`). Depth is now counted
  from the nearest enclosing project marker (`package.json`, `pyproject.toml`,
  `Cargo.toml`, and similar) under a hard absolute ceiling, so deep-but-legitimate
  layouts stay reachable while pathological trees remain bounded.

  Scan roots now also include the homes agent tools keep their scratch checkouts
  in (`~/.claude-worktrees`, `~/.codex/worktrees`, `~/.cursor/worktrees`) and
  `~/Documents/projects`. Roots, markers, depth policy and the prune list are
  shared across providers in `devdoctor.providers._walk`.

  On one real machine: `node_modules` 20.2 GB -> **32.1 GB** across 117
  directories, and `python-venvs` 195 MB -> **2.6 GB** across 31 (21 of that
  machine's 27 virtualenvs sat at depth 7 and had never been visible).
- **Scanning no longer skips dot-directories.** Three independent walkers — the
  project index, the virtualenv provider, and the large-file provider — each
  refused to descend into any directory starting with `.`, so anything inside an
  agent or git worktree (`.worktrees/`, `.claude/worktrees/`, `.codex/`) was
  structurally invisible. Pruning is now driven by an explicit, auditable list of
  names shared across all three (`devdoctor.providers._walk.PRUNE_DIR_NAMES`),
  which also gained the build and tool caches the dot-rule was implicitly
  covering (`.terraform`, `.next`, `.gradle`, `.mypy_cache`, and similar).

  On one real machine, surfaced `node_modules` went from 4.6 GB across 33
  directories to 20.2 GB across 75. Large files in hidden directories such as
  `~/Documents/.archive` are now reported. Virtualenvs inside worktrees are now
  reachable in principle, though most remain hidden behind the virtualenv
  provider's own depth cap until that is addressed separately.

  Behaviour change worth calling out: `large-files` previously skipped hidden
  directories by design, and no longer does.
- **Migrated the web and desktop toolchain from npm to Bun** — local scripts,
  CI, release builds, Electron packaging, dependency updates, and contributor
  docs now use the pinned Bun version and committed text lockfile.
- **Renamed the package and CLI from `diskdoctor` to `devdoctor`**, completing
  the transition that started with the repository rename. The installable
  package is now `devdoctor`, the command is `devdoctor`, and the
  `DISKDOCTOR_*` environment variables are now `DEVDOCTOR_*`. Existing local
  state in `~/.local/share/diskdoctor` keeps working: the new CLI falls back
  to it until a `devdoctor` data directory exists.

### Added

- **Agent session stores, offered by age.** Codex and Claude Code transcripts
  are the user's history, so the new `agent-sessions` family never offers them
  wholesale. `codex-sessions` and `claude-code-sessions` group sessions into
  fixed age buckets (under 30 days, 30 to 90, 90 to 180, 180 to 365, over a year), one
  entry each, as young as the bucket's newest member, so `--older-than 90d`
  selects whole buckets exactly. Buckets untouched for the retention floor
  (90 days; `DEVDOCTOR_SESSION_RETENTION_DAYS`, never under 30) are
  reclaimable with one delete per session; younger buckets are dangerous and
  advice only, even under `--allow-dangerous`. A Claude Code session is its
  transcript plus the directory beside it (subagents, tool results); `memory/`
  is never touched. `opencode-sessions` sizes OpenCode's SQLite database and
  counts its sessions by age read-only; no database is ever edited. The web
  recipe hint now counts an entry's further commands. (#84)
- **The iOS Simulator's dyld caches are covered.** `~/Library/Developer/
  CoreSimulator/Caches` held 1.3 GB on the machine that prompted #88 while the
  Xcode provider attributed only the unavailable simulators; `coresimulator-caches`
  offers it as a reclaimable deletion, rebuilt on the next simulator boot.
- **Terraform workspaces are covered, and the duplicate plugins are measured.**
  `terraform-workspaces` finds `.terraform` next to `.terraform.lock.hcl` or
  `main.tf` under the project roots and offers each as a reclaimable deletion
  (`terraform init` re-creates it). The plugin binaries under `providers/` are
  byte-identical across workspaces, so the scan adds up the copies of each
  plugin beyond the first and says what a shared `TF_PLUGIN_CACHE_DIR` would
  collapse: the lasting fix is configuration, not deletion. The scan's note
  header now reads "note(s) from the scan (skipped paths, tool advice)", since
  notes are no longer only about skipped paths. (#82)
- **AI agent and editor caches are covered.** Safe deletions for VS Code and
  Cursor extension package downloads, Cursor's staged updates and both
  editors' session logs; reclaimable deletions for Codex CLI runtimes and exo
  model weights; and one advice entry per editor for installed extensions
  (VS Code, Cursor, Windsurf), naming the editor's own uninstall command. The
  agent worktree homes were already covered by `git-worktrees`. Session and
  transcript stores stay untouched until #84 gives them age-based retention.
  (#83)
- **Twelve more developer caches are covered.** Safe deletions for
  pre-commit hook environments, Puppeteer browsers, node-gyp headers,
  Electron binaries, opam's download cache and Google's updater cache;
  Docling models as reclaimable; and one advice entry per installed rustup
  toolchain, nvm Node version and pyenv Python version, plus Vagrant boxes and
  Steampipe plugins, each naming its tool's own uninstall command, because one
  may be in use and a bare delete leaves the tool's index stale. About 10 GB
  on the machine that prompted this. (#88)
- **Colima is covered.** `colima-vm-disk` finds the Lima disk images under
  `~/.colima/_lima` (the data disk and each profile's diffdisk), reports what
  they occupy against what they reserve like `Docker.raw`, and is advice only:
  deleting a Lima disk destroys the VM's containers and volumes, so the guidance
  is to free space inside the VM or `colima stop` and `colima delete`.
  `colima-cache` offers the downloaded base images as a safe deletion. On the
  machine that prompted this: 7.1 GB of disks and 673 MB of cache that no
  provider saw. (#85)
- **The web Disk page filters by age and states its coverage.** An "untouched
  for" chip row (30d+, 90d+, 6mo+, 1y+) is the web form of `scan --older-than`:
  it narrows the rows already loaded, leaves entries of unknown age out, and
  runs no scan, like the risk chips. The totals row states how much of the
  volume's used space an unfiltered scan accounts for, the coverage line the
  CLI already printed. On the machine that prompted this, one click isolated
  24 GB of `node_modules` untouched for 90 days.
- **A scan says how much of the disk it accounts for.** DevDoctor reported 90 GB
  on a machine with 396 GB used and gave no hint that it was a quarter of the
  picture. Every unfiltered scan now ends with a coverage line, classified
  bytes against the volume's own used space, and `--json` carries a `coverage`
  object. `scan --coverage` also sizes the home directory outside every
  classified path and lists the ten largest directories no provider accounts
  for, which is how gaps in the provider catalogue used to be found by hand. On
  the reference machine it adds about 20 s to a 53 s scan. Used space comes
  from `df`, because on APFS total minus free also counts the system, swap and
  preboot volumes. (#81)
- **Sparse files are explained instead of silently under-reported.** Docker
  Desktop's `Docker.raw` is 80 GB long and occupies what Docker has written, so
  DevDoctor's figure and Finder's disagree by tens of gigabytes. Entries from
  path providers and `large-files` now carry `apparent_bytes` in `--json`, and
  `scan` prints a `Sparse:` note when an entry reserves at least 1 GiB and a
  tenth more than it occupies. The gap was never on the disk, so it is
  described and never offered as reclaimable. (#86)
- **`--older-than` on `scan` and `clean`, and `scan --sort age`.** Age was the
  deciding factor in every "is this safe to remove?" judgement, and every entry
  already carried its modification time. `--older-than 6mo` keeps only entries
  untouched that long (`12h`, `90d`, `2w`, `6mo`, `1y`); entries of unknown age
  are left out rather than assumed old. `--sort age` lists the longest untouched
  first. The table's `Stale?` column is now `Age`. (#89)
- **An entry's age is the newest modification anywhere inside it.** It was the
  top-level directory's own modification time, which does not move when a file
  deep inside is rewritten: Docker's `vms` directory read as 6.9 years old with
  an image written that day. The sizer already stats every file, so it reports
  the newest at no extra cost. The Time Machine bundle is likewise dated by the
  youngest snapshot it deletes, not the oldest, so an age filter can no longer
  offer it while it removes snapshots the filter excluded. (#89)
- **Time Machine local snapshots provider (`time-machine-local-snapshots`,
  macOS only).** Lists hourly APFS local snapshots via
  `tmutil listlocalsnapshots /` and offers one bundle that deletes all but the
  newest restore point (newest first), plus one entry per snapshot. macOS
  system-update snapshots (`com.apple.os.update-*`) are never touched, and
  deleting local snapshots never touches the external backup. Approving the
  bundle marks the per-snapshot entries `skipped:covered` — they are never
  prompted nor executed twice — and the `recipe` script lists the bundle's
  commands once, with covered snapshots as label-only lines.
- **`devdoctor history`** lists past cleanup runs — CLI and web UI now write one
  audit log — and shows a run entry by entry. `clean` gains `--yes` (skip the
  final confirmation only; the plan still prints) and `--risk`. (#126)
- **End-to-end docs.** `docs/` gains a tutorial written from a real
  14-to-70 GB session, a CLI reference, web UI guide, provider catalogue,
  safety model, FAQ, and agent docs; the landing page serves them under
  `site/docs/`, with `llms.txt` / `llms-full.txt` at the site root. (#125)
- **Live scan progress in the web UI.** While a scan runs, the Disk page shows
  how many providers have finished, the bytes found so far and which providers
  are running, ahead of the countdown from past scans; the Dashboard's loading
  label shows the provider count. The page reads a new server-sent-events
  endpoint, `GET /api/scan/progress`, that mirrors the scan running in the
  server; `GET /api/scan` is unchanged. (#117)
- **Hermetic end-to-end tests for the web UI.** Playwright now drives a
  `devdoctor serve` started under a throwaway home, with one YAML cache and one
  node project as fixtures, and runs in CI: the disk table and its risk chips,
  the cleanup wizard up to its review step, the dashboard total, auto-snapshots,
  and the providers page. (#105)
- **Git worktrees provider (`git-worktrees`).** Finds the linked worktrees of
  repositories under the project roots, including worktrees those repositories
  register elsewhere, and classifies each one without writing to the repository
  or using the network. A worktree whose changes are already in the default
  branch and that has no uncommitted changes is offered for removal with
  `git worktree remove`, never `--force`. Squash and rebase merges are detected
  with `git merge-tree` on git 2.38 or later; older git and partial clones detect
  only true merges and fast-forwards. A worktree containing a nested repository
  or worktree, even an ignored one, is never offered, because `git worktree
  remove` would delete it; nested repositories are detected by a `.git` entry or
  by a directory git recognises as a repository (`HEAD`, `objects/`, `refs/`),
  bare repositories included. Every other worktree is reported as advice: not
  integrated, uncommitted changes, contains nested repository, locked, broken
  pointer, no default branch, git error, or unverifiable. Contents of a removable
  worktree, such as `node_modules`, virtualenvs and build output, are counted
  once, under the worktree, instead of again by their own providers. The first
  `devdoctor diff` against an older snapshot therefore shows those bytes moving
  from their own providers to `git-worktrees` for removable worktrees.
  ([#79](https://github.com/katagun/devdoctor/issues/79))
- **Expanded provider coverage** — added pnpm, Yarn, Bun, bounded
  `node_modules`, Go caches, Cargo dependency/build storage, Xcode/iOS,
  Android SDK/build storage, Conda, NuGet, and tox/nox providers, grouped by
  stable ecosystem families.

- **CLI (`devdoctor`)** — repeatable disk-cache analysis and interactive
  cleanup for macOS and Linux: `scan`, `recipe`, `clean`, `snapshot`, `diff`,
  and `providers`, with a preview-first safety model and explicit
  safe/reclaimable/dangerous labels. Providers cover Ollama, LM Studio, Docker,
  and Hugging Face, plus a set of YAML-defined cache paths.
- **Local web UI (`devdoctor serve`)** — a FastAPI backend and React
  dashboard with a size treemap, per-provider details, and live scan/cleanup
  over server-sent events.
- **Electron desktop app packaging (macOS)** — a desktop shell that bundles the
  web UI and a standalone (PyInstaller) copy of the backend, so the app runs
  with no separate Python install; first-run flow waits for the backend and
  points users at Full Disk Access.
  ([#5](https://github.com/katagun/devdoctor/issues/5))
- **Structured logging and a scan diagnostics channel** — a `-v/--verbose`
  flag, no more silently-swallowed errors, and scans now surface skipped paths
  (for example, permission denied) instead of looking empty.
  ([#10](https://github.com/katagun/devdoctor/issues/10))
- **Virtualized cache table** — the web UI windows its rows, so scans with
  thousands of entries render only the visible slice.
  ([#8](https://github.com/katagun/devdoctor/issues/8))
- **Versioned SQLite migration runner** — a real migration path so the local
  history schema can evolve without breaking existing databases.
  ([#11](https://github.com/katagun/devdoctor/issues/11))
- **Public project surface** — a
  [landing page](https://katagun.github.io/devdoctor/), a public
  [roadmap](ROADMAP.md), and community docs (CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, issue and PR templates).
- **CI and repository hardening** — GitHub Actions CI (Python and web), CodeQL
  scanning, Dependabot, web ESLint, and CODEOWNERS.

### Changed

- **Made disk-byte semantics explicit** — reports and snapshots now distinguish
  filesystem footprint, estimated reclaimable space, and shared allocations;
  cleanup history no longer presents estimates as verified bytes freed.
- **Introduced typed cleanup actions** — path deletion, argv commands, and
  non-executable advice replace shell-like execution while old snapshots and
  generated commented scripts remain compatible.
- **Made shared-file accounting deterministic** — hard-linked allocations are
  reconciled after concurrent discovery and recalculated for the complete
  selected cleanup plan without double-counting overlapping entries.

- **Rebranded to DevDoctor** — the product is now DevDoctor and ships a public
  landing page; the Python package and CLI stay named `devdoctor` during the
  transition, with copyright attributed to embark-delve.
- **Parallelized provider discovery** — discovery runs concurrently in a
  bounded thread pool, with identical, deterministic output.
  ([#9](https://github.com/katagun/devdoctor/issues/9))
- **Modernized the web toolchain** — migrated the UI to react-router 7 and
  upgraded to Vite 8 and Vitest 4.
- **Made the desktop backend build reproducible** — the packaged backend is
  built with the required extras so the bundle is consistent.

### Fixed

- **The e2e harness no longer reaches Docker Desktop's bundled CLI.** Its server
  runs with no `docker` on PATH, so the Docker provider fell back to Docker
  Desktop's CLI and, with Docker running, would have put the machine's real
  images, volumes and build cache into the fixture scan.
  `DEVDOCTOR_DOCKER_BUNDLED_CLI` now points that fallback at another path, or
  turns it off when empty, as the harness and the Python tests do.
- **Cleaning the uv cache no longer hangs when DevDoctor runs under `uv run`.**
  `uv run` and `uvx` hold the uv cache lock until the program they started
  exits, so the `uv cache clean` they spawned waited for that lock forever and
  the 5.9 GB cache stayed. The `uv-cache` provider now asks `uv cache dir`
  where the cache is (so `UV_CACHE_DIR` is honoured), passes `--force` when it
  detects a parent uv process, and says so in the scan's diagnostics; without
  uv on PATH it deletes the directory. (#127)
- **A file that occupies nothing is counted as nothing.** Zero allocated blocks
  was read as "this filesystem hides block counts" and the file was counted at
  its full length, so a VM disk image that had never been written to read as
  its whole size limit, and no `Sparse:` note appeared for it. Only a platform
  with no block counts at all falls back to the length now. Symlinks, whose
  length is their target path and which occupy no blocks, stop contributing a
  few bytes each: about 2 KB on a 700 MB `node_modules`. (#86)
- **A path provider that names a file reports its size.** Sizing walked
  directories only, so a model matched by `*.gguf` sized to zero, was dropped
  from the scan, and left a misleading "permission denied or vanished"
  diagnostic. (#86)
- **The Docker disk image advice no longer walks users into data loss.** It
  suggested lowering the disk image size limit when usage was small; per
  Docker's documentation that deletes the image and every container, image and
  volume in it, which the text did not say. The advice now explains that space
  freed inside Docker returns to macOS when the image is compacted, gives the
  command that forces it, and names what the destructive options destroy. (#86)
- **Risk chips no longer rerun the scan, the estimate counts down, and the
  Dashboard and Disk pages share one scan.** Each chip click used to send a new
  `risk` filter to the server and wait for a full scan (minutes on a large
  machine); the chips now narrow the rows already loaded, while the API and CLI
  keep server-side filtering. The "scanning…" estimate now counts down from the
  past-scan figure, uses the newest scan as a floor so a scan that grew is not
  underestimated, and says when it has run longer than past scans. Opening the
  Dashboard and then the Disk page runs one scan, not two: the Dashboard now
  follows the scan cadence setting instead of always rescanning, and
  auto-snapshots are written at most every five minutes whatever the cadence,
  so the "Live" setting no longer fills the history with same-minute scans.
  Streaming per-provider progress is tracked in #117. (#104)
- **The dashboard's estimated reclaimable total no longer reads as zero.** The
  cached disk summary the dashboard reads was written with the scan's reclaimable
  and footprint figures but handed to the page without them, at the summary,
  entry and provider level, so the tile showed the footprint until a live scan
  finished. (#102)
- **The cleanup button pluralises its count.** One selected row now reads
  "clean up 1 item", not "1 items". (#106)
- **Cleanup re-checks each git worktree immediately before removing it.** Git
  never re-checks whether a worktree is still integrated, so a commit made after
  the scan, especially on a detached HEAD, could be lost when cleanup removed the
  worktree. `devdoctor clean` and the web cleanup now re-classify every worktree
  right before `git worktree remove` and skip any that changed, with the reason.
  A worktree that could not be re-checked at all, for example because git failed,
  is skipped with a separate "could not re-check" message instead of being
  reported as changed.
  ([#110](https://github.com/katagun/devdoctor/issues/110),
  [#114](https://github.com/katagun/devdoctor/issues/114))
- **Filtered web scans no longer save partial auto-snapshots.** A scan with a
  risk, size or provider filter could be stored as an auto-snapshot and show up
  in history as a large drop followed by an equal jump. Only unfiltered scans are
  stored now. ([#103](https://github.com/katagun/devdoctor/issues/103))
- **The web UI shows unmeasured entries as not measured instead of 0 B.** They
  sort after measured rows and are never hidden as small by the minimum-size
  setting. ([#97](https://github.com/katagun/devdoctor/issues/97))
- **Made Docker volume cleanup precise and version-independent** — unused
  volumes are now listed individually instead of pairing Docker's aggregate
  volume size with version-dependent `docker volume prune` behavior. Anonymous
  volumes are reclaimable, named volumes require explicit dangerous-cleanup
  consent, and the web cleanup flow now carries that consent to the backend.
- **De-flaked the SSE lifecycle test** — it now runs on a pre-bound socket with
  no port race, and drops deprecated `websockets` APIs.
  ([#14](https://github.com/katagun/devdoctor/issues/14))
- **The Docker provider finds Docker Desktop's bundled CLI when `docker` is
  not on PATH.** On macOS the provider now falls back to
  `/Applications/Docker.app/Contents/Resources/bin/docker`, runs discovery
  and cleanup through that binary, and records a diagnostic naming it — so a
  missing `/usr/local/bin` symlink no longer hides Docker reclaimable space.
  ([#123](https://github.com/katagun/devdoctor/issues/123))

### Security

- **Path traversal** in snapshot handling has been closed.
- **Command injection** into the generated cleanup script is prevented — model
  names and paths are `shlex`-quoted and destructive lines stay commented out.
- **Terminal-escape injection** via crafted filenames in rendered output has
  been neutralized.
- **Stale-PID kill** in the memory tooling was fixed so it can't target a
  reused process id.
- **Data-loss mislabels** were corrected — directories that mix cache with real
  user data are now labelled dangerous rather than reclaimable.
- **Cross-provider entry-id collisions** are prevented by namespacing entry ids
  per provider, so cleanup selection can't mis-route between providers.
  ([#12](https://github.com/katagun/devdoctor/issues/12))
- **Supply-chain hardening** — third-party GitHub Actions are pinned to commit
  SHAs, and CodeQL plus Dependabot keep code and dependencies under watch.

[Unreleased]: https://github.com/katagun/devdoctor/commits/main
