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

- **Made Docker volume cleanup precise and version-independent** — unused
  volumes are now listed individually instead of pairing Docker's aggregate
  volume size with version-dependent `docker volume prune` behavior. Anonymous
  volumes are reclaimable, named volumes require explicit dangerous-cleanup
  consent, and the web cleanup flow now carries that consent to the backend.
- **De-flaked the SSE lifecycle test** — it now runs on a pre-bound socket with
  no port race, and drops deprecated `websockets` APIs.
  ([#14](https://github.com/katagun/devdoctor/issues/14))

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
