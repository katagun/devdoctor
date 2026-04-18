# diskdoctor — Design

Date: 2026-04-18
Status: Draft (v2, post self-review)

## Purpose

A repeatable, inspectable CLI for analyzing disk usage on macOS and Linux, focused on the caches and artifacts that actually consume real space on a developer's machine — model caches, container VMs, package-manager caches, browser data. Produces a human report, a machine-readable JSON report, a reviewable shell script of cleanup commands, and an interactive (dry-run-by-default) cleanup mode. Snapshots enable tracking cache growth over time.

## Non-goals

- Not a general filesystem analyzer (not an `ncdu` replacement).
- Not a Windows tool.
- Not a background daemon. Every action is explicit, foreground, idempotent.
- No telemetry, no unsolicited network calls.
- Not a hard dependency on any vendor CLI; the tool degrades gracefully when a CLI is absent.

## Top-level decisions

| Decision | Choice |
|---|---|
| Scope | Report + action recipes + interactive cleanup |
| Provider architecture | Hybrid — Python classes for caches with real logic; a YAML-driven `PathProvider` (with glob support) for every cache that is "just a directory" |
| Safety model | Dry-run by default; per-item prompts; final confirm summary; risk-tiered display |
| History | On-demand JSON snapshots in `~/.local/share/diskdoctor/snapshots/` |
| Platforms | macOS + Linux |
| Python / packaging | `uv` + `pyproject.toml`, Python 3.12+, installable via `uv tool install` |
| CLI name / repo | `diskdoctor` |
| Recipe output | Per-cache snippets and full script both supported |
| Machine output | `--json` flag on `scan` |

## Design principles

- **KISS**: prefer YAML + one generic provider over a new class.
- **DRY**: shared behavior (platform gating, binary-on-PATH check, sizing, path interpolation) lives once in the base.
- **DIP**: providers and core depend on narrow ports (`Shell`, `Clock`, `Filesystem`) — never on `subprocess`, `time`, or `os` directly. Real implementations are injected in production; fakes in tests.
- **DDD**: bounded contexts (discovery, cleanup, history, rendering) are separate modules; the ubiquitous language (Entry, Recipe, Risk, Snapshot) is used consistently.
- **TDD**: every unit has a failing test written first. Ports make this tractable — no `subprocess` mocking, just fake Shell.

## Architecture

Four bounded contexts, one module each:

1. **discovery** — orchestrates providers, sizes entries, returns a `Report`. Pure function of `(registry, filters, clock, fs) -> Report`.
2. **cleanup** — interactive prompt loop, dry-run vs execute, final confirm. Pure function of `(report, prompter, shell) -> list[CleanResult]`. Also builds the shell-script text for `recipe`.
3. **history** — read/write snapshot JSON files, compute diffs between two reports (or snapshot vs live).
4. **rendering** — Rich tables/progress/prompts and JSON serialization. Pure; takes a `Report` or `list[CleanResult]` and returns text or writes to a stream.

A fifth module, **registry**, loads the list of providers (built-in classes + YAML-backed `PathProvider` instances) and is the composition root.

`cli.py` is the composition root at runtime: it wires real implementations of the ports (`RealShell`, `RealClock`, `RealFilesystem`) into `registry.load_providers()`, calls into the appropriate context, and prints the result via `rendering`.

### Data flow

```
cli
 ↓  parse args; wire ports
registry.load_providers()   → list[Provider]
 ↓
discovery.scan(providers, filters)
 ↓  Provider.discover(); sizer sizes Entry.path
Report  (dataclass)
 ↓
rendering.table(Report) → Rich      OR  rendering.json(Report) → stdout
                                    OR  cleanup.run(Report, prompter, shell) → list[CleanResult]
                                    OR  history.write_snapshot(Report) / history.diff(a, b)
```

## Ports (dependency inversion)

Three small protocols. Every non-trivial unit depends on one or more of these — never on `subprocess`, `datetime`, or the real filesystem directly.

```python
class Shell(Protocol):
    def run(self, argv: list[str], *, check: bool = True) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...

class Clock(Protocol):
    def now(self) -> datetime: ...

class Filesystem(Protocol):
    def exists(self, path: Path) -> bool: ...
    def walk(self, root: Path) -> Iterator[tuple[Path, list[str], list[str]]]: ...
    def lstat(self, path: Path) -> os.stat_result: ...
    def rmtree(self, path: Path) -> None: ...
```

Test doubles:
- `FakeShell(responses: dict[tuple, ShellResult])` — deterministic
- `FixedClock(value: datetime)`
- `InMemoryFilesystem` — optional; for most tests real `tmp_path` is simpler than faking FS

## Components

### File layout

```
diskdoctor/
├── pyproject.toml                   uv + hatchling; console_scripts = diskdoctor
├── README.md
├── LICENSE                          MIT
├── .gitignore .python-version .pre-commit-config.yaml
├── src/diskdoctor/
│   ├── __init__.py
│   ├── cli.py                       Click group; composition root
│   ├── types.py                     Risk, Entry, Report, CleanResult, ShellResult
│   ├── ports.py                     Shell, Clock, Filesystem Protocols + Real impls
│   ├── sizer.py                     size_path(fs, root) — symlink-safe, one device
│   ├── registry.py                  load_providers(shell, fs)
│   ├── discovery.py                 scan(providers, filters, clock) -> Report
│   ├── cleanup.py                   run(report, shell, prompter, opts) -> list[CleanResult]; build_script(report)
│   ├── history.py                   write_snapshot, load_snapshot, diff
│   ├── rendering.py                 Rich tables, progress, prompts; JSON serializer
│   ├── data/paths.yaml              declarative entries for simple caches
│   └── providers/
│       ├── __init__.py
│       ├── base.py                  Provider ABC; PathProvider (YAML + glob)
│       ├── ollama.py                daemon-or-walk: prefer `ollama list`, fall back to walking ~/.ollama/models
│       ├── docker.py                `docker system df` parsing; clean via `docker system prune`
│       ├── lm_studio.py             walks ~/.cache/lm-studio/models, groups by publisher/model
│       └── huggingface.py           walks ~/.cache/huggingface/hub, groups by repo, symlink-safe
├── tests/
│   ├── conftest.py                  fakes: FakeShell, FixedClock; fixture builders
│   ├── test_sizer.py
│   ├── test_registry.py
│   ├── test_path_provider.py
│   ├── test_ollama_provider.py
│   ├── test_docker_provider.py
│   ├── test_lm_studio_provider.py
│   ├── test_huggingface_provider.py
│   ├── test_discovery.py
│   ├── test_cleanup.py
│   ├── test_history.py
│   └── test_cli.py                  Click CliRunner; one happy path + one error path per command
└── docs/superpowers/specs/
    └── 2026-04-18-diskdoctor-design.md
```

### Types

```python
class Risk(str, Enum):
    SAFE = "safe"                   # zero cost to regenerate
    RECLAIMABLE = "reclaimable"     # regenerable but costs time/bandwidth (models)
    DANGEROUS = "dangerous"         # holds real state; app workspaces, logs

@dataclass(frozen=True)
class Entry:
    provider: str                   # e.g. "ollama"
    id: str                         # provider-scoped unique id (model tag, path)
    path: Path | None               # None for logical-only items (e.g. docker image)
    label: str                      # shown in tables
    size_bytes: int
    mtime: float | None             # epoch; None when not meaningful
    risk: Risk
    recipe: list[str]               # shell commands to clean this entry

@dataclass
class Report:
    entries: list[Entry]
    scanned_at: datetime
    hostname: str
    platform: str                   # "darwin" | "linux"
    note: str | None = None
    skipped_paths: list[str] = field(default_factory=list)  # permission denied etc.
    # methods: by_provider(), total_bytes(), filter_by_risk(), to_json(), from_json()

@dataclass
class CleanResult:
    entry_id: str
    status: Literal["ok", "skipped", "error", "dry_run"]
    freed_bytes: int
    message: str | None = None

@dataclass
class ShellResult:
    returncode: int
    stdout: str
    stderr: str
```

### Provider contract

```python
class Provider(ABC):
    name: str
    description: str
    platforms: tuple[str, ...]           # ("darwin", "linux")
    risk: Risk
    required_binary: str | None = None   # e.g. "docker"; None for pure-path providers

    def __init__(self, shell: Shell, fs: Filesystem): ...

    def available(self) -> bool:
        # default: current platform in self.platforms AND (required_binary is None or shell.which(required_binary))
        ...

    @abstractmethod
    def discover(self) -> list[Entry]: ...

    def recipe(self, entry: Entry) -> list[str]:
        return list(entry.recipe)

    def clean(self, entry: Entry, dry_run: bool) -> CleanResult:
        # default: iterate entry.recipe, shell.run each; aggregate freed_bytes
        ...
```

`PathProvider` is the workhorse: one instance per YAML entry, `discover()` expands globs in the configured paths, sizes via the injected FS, and builds Entries with the per-entry recipe string templated with `{path}`.

### `paths.yaml` schema

```yaml
- name: lm-studio-extensions
  description: LM Studio extension downloads
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/lm-studio/extensions
  recipe: "rm -rf {path}"

- name: uv-cache
  description: uv package cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/uv
  recipe: "uv cache clean"

- name: chrome-cache
  description: Chrome browser cache (all profiles)
  risk: safe
  platforms: [darwin]
  paths:
    - ~/Library/Caches/Google/Chrome/*/Cache
  recipe: "rm -rf {path}"
```

Rules:
- `paths` entries are tilde- and `${HOME}`-expanded, then glob-expanded.
- `{path}` in `recipe` is interpolated per matched path.
- Risk and platform strings are validated against the `Risk` enum and a fixed platform set at load time; malformed YAML is a startup error with the offending entry.

### Non-trivial providers (why they need a class, not YAML)

- **ollama.py** — `discover()` tries `shell.run(["ollama", "list"])` first (parsed to `Entry` per model with logical id `<name>:<tag>`); on daemon failure, falls back to walking `~/.ollama/models` and emitting one Entry per model directory. Clean uses `ollama rm <name>` when the CLI path succeeded, else `rm -rf` on the model path.
- **docker.py** — `discover()` reads `docker system df --format json`; produces one Entry per category (images/containers/volumes/build-cache). Clean uses `docker system prune` variants.
- **lm_studio.py** — walks `~/.cache/lm-studio/models`, groups into `publisher/model` entries, so users can cleanup individual models.
- **huggingface.py** — walks `~/.cache/huggingface/hub` producing one Entry per `models--<org>--<name>` or `datasets--<org>--<name>` directory; the sizer handles the `blobs/`+`snapshots/` symlink structure (see below). Uses the optional `huggingface_hub` Python package if importable for nicer labels; never requires the CLI.

### Sizer behavior (explicit)

`size_path(fs, root) -> (bytes, skipped: list[Path])`:
- Walks `root` with `followlinks=False`.
- Uses `lstat` on every entry; regular files → add `st_size`, symlinks → size of the link itself (usually negligible), directories → recurse.
- If `lstat(root).st_dev != st_dev` of a subtree, skip that subtree (defends against nested mounts).
- `PermissionError` / `FileNotFoundError` on any entry → add to `skipped` list, keep going.
- HF cache: because snapshots are directories of symlinks pointing into `blobs/`, this strategy correctly counts blobs once and skips the symlinks — matching `huggingface-cli scan-cache`'s accounting.

## CLI surface

```
diskdoctor scan [--json] [--min-size SIZE] [--risk safe,reclaimable,dangerous]
    Rich table: Name | Path | Size | Risk | Stale? | Recipe hint
    Sort desc by size; footer totals; progress bar during sizing.
    --json suppresses rendering, emits Report schema to stdout.
    SIZE syntax: "500M", "2G", "100K" (base-10). Plain integers = bytes.
    --risk accepts a comma-separated list; unknown values are a user error.

diskdoctor recipe [NAME...] [-o FILE] [--executable]
    No args    → full script to stdout, header comment, all providers, commented sections.
    With names → only those providers' sections.
    -o         → write to file.
    --executable → emit uncommented destructive lines (default: commented out).

diskdoctor clean [NAME...] [--execute] [--yes-safe] [--allow-dangerous]
    Default is a DRY RUN.
    With --execute:
      - per-entry prompt: [y/N/a=all-in-provider/s=skip-provider/q=quit]
      - --yes-safe        auto-approves SAFE entries
      - --allow-dangerous required to even prompt for DANGEROUS
      - after walking entries, Rich summary (count, est bytes) → final y/N
      - execute; print result table of freed bytes and failures

diskdoctor snapshot [--note TEXT]
    Runs a scan, writes ~/.local/share/diskdoctor/snapshots/<ISO8601>.json.
    Schema matches --json output plus note, hostname, platform.

diskdoctor diff [--from SNAPSHOT] [--to SNAPSHOT|live]
    Defaults: latest vs second-latest.
    Rich table: provider | before | after | Δ bytes | Δ % (green=shrunk, red=grew)

diskdoctor providers
    Lists every registered provider: name, risk, platforms, available?, path exists?
```

Exit codes:
- `0` — success (including a no-op dry run)
- `1` — user error (bad args, unknown provider)
- `2` — scan/clean completed with per-entry failures
- `130` — interrupted (SIGINT)

## Error handling

- **Missing external CLI** (no `ollama`, `docker` on PATH): `available()` returns False; `scan` lists the provider as unavailable and skips it. Never an unhandled exception.
- **Ollama daemon not running**: `discover()` catches the non-zero from `ollama list` and falls back to walking the models directory.
- **Permission denied while sizing**: recorded in `Report.skipped_paths`; footer shows a one-line count.
- **Symlinks and cross-device**: handled by the sizer (see above).
- **Clean failures**: one entry's failure does not abort the run. Result table shows per-entry status; exit code becomes `2`.
- **SIGINT during interactive clean**: cancel remaining prompts; print "nothing executed" if the final confirm has not yet been given; otherwise partial-execution summary.
- **Malformed `paths.yaml`**: fail loudly at startup with the offending entry and validation error. Plain-dataclass validation, no Pydantic dependency.

## Testing (TDD)

Every unit starts with a failing test. Ports keep tests fast and hermetic.

Per-module coverage:
- **sizer** — trees with regular files, symlinks (including loops), permission denied, cross-device; uses real `tmp_path` (faster and more honest than faking FS for this module).
- **registry** — loads YAML, rejects malformed entries with location info; combines YAML providers + class providers; deterministic alphabetical order.
- **PathProvider** — path expansion (`~`, `${HOME}`), globbing, `{path}` recipe templating.
- **Provider classes** — each tested with `FakeShell`:
  - ollama: `list` success parsing; `list` failure → walk-dir fallback
  - docker: `system df --format json` parsing; handles missing docker binary
  - lm_studio: per-`publisher/model` entry generation from a `tmp_path` tree
  - huggingface: `hub/models--*` grouping; symlink-safe sizing verified against a constructed blob+snapshot tree
- **discovery.scan** — with a small fake registry, confirms filtering, sorting, and totals.
- **cleanup.run** — dry-run produces no shell calls; execute path with a scripted prompter covers y/N/a/s/q and the final confirm; failures propagate to `CleanResult.status`.
- **cleanup.build_script** — golden-file style: given a Report, assert exact script text.
- **history** — snapshot JSON round-trip; diff computes Δ correctly including added/removed providers.
- **CLI** — Click `CliRunner` for one happy path and one error path per command; wiring is real but ports are injected via test-only factory to use fakes.

Coverage target: core modules (sizer, discovery, cleanup, history, registry) ≥ 90%; providers ≥ 80%; CLI lower.

## Out of scope for v1

- Remote-host scanning (SSH).
- Scheduled background runs.
- GUI.
- Third-party provider plugin discovery (ten-line `importlib.metadata` addition if demanded).
- Auto-upload of snapshots.

## Future extensions

- `diskdoctor watch <cache>` — alert when a cache crosses a threshold.
- Grafana/Prometheus exporter for snapshot JSON.
- `--parallel` sizing if cold scans become slow (expected: seconds on this machine).
- Homebrew tap or `uv tool install --from git+...` publication path.

## Changes from v1 (self-review)

- Split `core.py` into four domain-aligned modules (`discovery`, `cleanup`, `history`, `rendering`).
- Collapsed `recipes.py` into `cleanup.py` (not enough there for its own module).
- Introduced three ports (`Shell`, `Clock`, `Filesystem`) so providers and core don't touch `subprocess`/`datetime`/real FS directly — unlocks clean TDD.
- Moved `available()` default behavior (platform gating + `which <binary>`) into `Provider` base class. Removed per-provider boilerplate.
- Replaced `homebrew.py`, `browser.py`, and `claude_vm.py` provider classes with YAML entries (plus glob support in `PathProvider`). Four classes only for caches that actually need logic.
- Called out HF cache symlink semantics; made `huggingface-cli` explicitly optional (binary not assumed present).
- Added Ollama daemon-fallback behavior (daemon is commonly off while models sit on disk).
- Expanded the testing section with per-module coverage and explicit TDD stance.
