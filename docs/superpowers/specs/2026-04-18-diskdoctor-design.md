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
- **DIP**: providers and core depend on narrow seams. Only one true port — `Shell` — because that's the only side effect worth faking. Time is passed in as a `datetime` parameter. Filesystem work uses `pathlib` + `tmp_path` in tests. Prompting is a typed `Callable`.
- **DDD**: three bounded contexts (`discovery`, `cleanup`, `history`) as separate modules. `rendering` is a cross-cutting presentation layer, not a domain. The ubiquitous language (Entry, Recipe, Risk, Report) is used consistently.
- **TDD**: every unit has a failing test written first. The narrow Shell port + real `tmp_path` make this tractable without heavy mocking machinery.

## Architecture

Three bounded contexts, one module each:

1. **discovery** — orchestrates providers, returns a `Report`. `scan(providers, filters, now) -> Report`. `Provider.discover()` populates `Entry.size_bytes` itself (using the `sizer` helper for path-based entries); `discovery.scan` does not re-size.
2. **cleanup** — interactive prompt loop, dry-run vs execute, final confirm, script emission. `run(report, shell, prompt, opts) -> list[CleanResult]` and `build_script(report) -> str`.
3. **history** — snapshot JSON files on disk and diffing. `write_snapshot(report, dir) -> Path`, `load_snapshot(path) -> Report`, `diff(before, after) -> DiffReport`.

Plus one presentation layer and one composition module:

- **rendering** — Rich tables/progress/prompts; writes `Report.to_json()` to a stream for machine output. Pure; takes domain objects, returns or writes text.
- **registry** — composition root for providers. Explicit imports of each class provider; constructs `PathProvider` instances from `paths.yaml`. `load_providers(shell) -> list[Provider]`.

`cli.py` is the runtime composition root: constructs `RealShell`, builds the real Rich-backed `prompt` callable, calls `registry.load_providers(shell)`, dispatches to a context, renders the result.

### Data flow

```
cli
 ↓  parse args; construct RealShell, prompt callable, now=datetime.now()
registry.load_providers(shell)   → list[Provider]
 ↓
discovery.scan(providers, filters, now)   # providers self-populate Entry.size_bytes
Report  (dataclass)
 ↓
rendering.table(Report) → stdout           OR  Report.to_json() → stdout
                                           OR  cleanup.run(Report, shell, prompt, opts) → list[CleanResult]
                                           OR  history.write_snapshot(Report, dir) / history.diff(a, b)
```

## Ports (dependency inversion)

One port — `Shell` — plus one typed callable alias — `Prompt`. That's it. Everything else is passed as plain data or uses the stdlib directly against `tmp_path` in tests.

```python
@dataclass(frozen=True)
class ShellResult:
    returncode: int
    stdout: str
    stderr: str

class Shell(Protocol):
    def run(self, argv: list[str], *, check: bool = False) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...

Choice = Literal["y", "N", "a", "s", "q"]
Prompt = Callable[[Entry], Choice]  # stateless; cleanup.run manages aggregate state
```

Why only one port:
- `datetime` — pass as a parameter to `scan` / snapshot code. `datetime.now()` in CLI, fixed value in tests. Simpler than a Clock Protocol.
- `filesystem` — `pathlib.Path` + `os.walk` work fine; tests use `tmp_path` fixtures (honest trees of real files). A `Filesystem` Protocol would be indirection with no test payoff.
- `prompt` — single method, stateless, typed `Callable` beats a Protocol.

Real impls live in `ports.py` (`RealShell`); the Rich-backed prompt is a one-line function in `rendering.py`. Fakes in tests:
- `FakeShell(responses: dict[tuple[str, ...], ShellResult])` — argv-keyed, deterministic.
- Test prompts are plain functions, often `itertools.cycle(...)` or a `list.pop(0)` closure.

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
│   ├── cli.py                       Click group; runtime composition root
│   ├── types.py                     Risk, Entry, Report, DiffReport, CleanResult, Choice, Prompt
│   ├── ports.py                     Shell Protocol; ShellResult; RealShell
│   ├── sizer.py                     size_path(root) -> (bytes, skipped) — symlink-safe, one device
│   ├── registry.py                  explicit list of class providers + YAML loader; load_providers(shell)
│   ├── discovery.py                 scan(providers, filters, now) -> Report
│   ├── cleanup.py                   run(report, shell, prompt, opts) -> list[CleanResult]; build_script(report)
│   ├── history.py                   write_snapshot, load_snapshot, diff
│   ├── rendering.py                 Rich tables/progress/prompts; real Prompt factory
│   ├── data/paths.yaml              declarative entries for simple caches
│   └── providers/
│       ├── __init__.py
│       ├── base.py                  Provider ABC; PathProvider (YAML + glob)
│       ├── ollama.py                daemon-or-walk: prefer `ollama list`, fall back to walking ~/.ollama/models
│       ├── docker.py                `docker system df` parsing; clean via `docker system prune`
│       ├── lm_studio.py             walks ~/.cache/lm-studio/models, groups by publisher/model
│       └── huggingface.py           walks ~/.cache/huggingface/hub, groups by repo, symlink-safe
├── tests/
│   ├── conftest.py                  FakeShell; scripted-Prompt builder; tmp-tree fixtures
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

    def by_provider(self) -> dict[str, list[Entry]]: ...
    def total_bytes(self) -> int: ...
    def filter(self, risks: set[Risk] | None = None, min_size: int = 0,
               providers: set[str] | None = None) -> "Report": ...
    def to_json(self) -> str: ...
    @classmethod
    def from_json(cls, data: str) -> "Report": ...

@dataclass
class CleanResult:
    entry_id: str
    status: Literal["ok", "skipped", "error", "dry_run"]
    freed_bytes: int
    message: str | None = None

@dataclass(frozen=True)
class DiffRow:
    provider: str
    before_bytes: int
    after_bytes: int
    delta_bytes: int
    delta_pct: float                # 0.0 when before_bytes == 0 and after_bytes == 0

@dataclass
class DiffReport:
    before_at: datetime
    after_at: datetime
    rows: list[DiffRow]             # includes added (before=0) and removed (after=0) providers
```

`Report.to_json`/`from_json` is the single canonical serializer. `rendering.py` writes the string; snapshots store the string; `--json` prints the string. One representation everywhere.

### Provider contract

```python
class Provider(ABC):
    name: str
    description: str
    platforms: tuple[str, ...]           # ("darwin", "linux")
    risk: Risk
    required_binary: str | None = None   # e.g. "docker"; None for pure-path providers

    def __init__(self, shell: Shell) -> None: ...

    def available(self) -> bool:
        # default: sys.platform in self.platforms
        # AND (required_binary is None or shell.which(required_binary) is not None)
        ...

    @abstractmethod
    def discover(self) -> list[Entry]: ...
        # Must fully populate each Entry — size_bytes, recipe, mtime, risk.
        # Path-based providers call `sizer.size_path(path)`. Logical providers
        # (ollama via `ollama list`, docker via `system df --format json`) derive
        # size from the external tool's output. Recipes are fully-formed shell
        # commands with any paths/IDs already interpolated — cleanup does not
        # re-template.
```

`Provider` has exactly two responsibilities: tell us if it's available, and discover its entries. Execution is a uniform concern handled by `cleanup` against `entry.recipe`, so there is no `Provider.clean()`. Docker's per-category pruning is encoded as distinct Entries with the appropriate `docker system prune` / `volume prune` command each — the Provider is a pure read model.

`PathProvider` is the workhorse: one instance per YAML entry. `discover()` expands `~`/`${HOME}` and globs in `paths`, calls `sizer.size_path` on each resolved path, builds Entries with the recipe string interpolated with the concrete `{path}`. The Entry's recipe is fully-formed — no downstream templating.

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

Each stamps the Entry's recipe with fully-formed shell commands at discover time.

- **ollama.py** — `discover()` tries `shell.run(["ollama", "list"])` first (parsed to one Entry per model, `id = "<name>:<tag>"`, `recipe = ["ollama rm <name>:<tag>"]`). On daemon failure (non-zero return), falls back to walking `~/.ollama/models` and emits one Entry per model directory with `recipe = ["rm -rf <path>"]`.
- **docker.py** — `discover()` parses `docker system df --format json`; emits one Entry per category (images / containers / volumes / build-cache), each with its own targeted prune recipe (`docker image prune -a -f`, `docker volume prune -f`, etc.). Categories with zero bytes are omitted.
- **lm_studio.py** — walks `~/.cache/lm-studio/models`, emits one Entry per `<publisher>/<model>` directory with `recipe = ["rm -rf <path>"]` so models can be cleaned individually.
- **huggingface.py** — walks `~/.cache/huggingface/hub` and emits one Entry per `models--<org>--<name>` or `datasets--<org>--<name>` directory. The sizer handles the `blobs/`+`snapshots/` symlink structure. Optionally imports `huggingface_hub` for prettier labels if the package is installed; never requires the CLI binary.

### Sizer behavior (explicit)

`size_path(root: Path) -> tuple[int, list[Path]]`:
- Walks `root` with `os.walk(..., followlinks=False)`.
- Uses `lstat` on every entry; regular files → add `st_size`, symlinks → size of the link itself (usually negligible), directories → recurse.
- Records `lstat(root).st_dev`; if any subtree's `st_dev` differs, skip that subtree (defends against nested mounts).
- `PermissionError` / `FileNotFoundError` / `OSError` on any entry → append to `skipped`, continue.
- HF cache: because snapshots are directories of symlinks pointing into `blobs/`, this strategy correctly counts blobs once and skips the symlinks — matching `huggingface-cli scan-cache`'s accounting.
- Uses stdlib only; tests pass real `tmp_path` trees. No filesystem abstraction.

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
- **cleanup.run** — dry-run produces no shell calls; execute path with a scripted `Prompt` callable covers y/N/a/s/q and the final confirm; failures propagate to `CleanResult.status`.
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

- Split `core.py` into three domain-aligned modules (`discovery`, `cleanup`, `history`) plus `rendering` as a cross-cutting presentation layer.
- Collapsed `recipes.py` into `cleanup.py`.
- Moved `available()` default behavior (platform gating + `which <binary>`) into `Provider` base class.
- Replaced `homebrew.py`, `browser.py`, and `claude_vm.py` provider classes with YAML entries (plus glob support in `PathProvider`).
- Called out HF cache symlink semantics; made `huggingface-cli` explicitly optional.
- Added Ollama daemon-fallback behavior.

## Changes from v2 (second self-review)

- **Dropped `Clock` port** — `scan(...)` takes `now: datetime` as a parameter.
- **Dropped `Filesystem` port** — `sizer` and providers use `pathlib` + `os.walk` directly; tests use real `tmp_path` trees.
- **Dropped `Provider.recipe()` method** — `entry.recipe` is the single source of truth, fully-formed at `discover()` time. No downstream templating.
- **Dropped `Provider.clean()` method** — recipes are fully-formed shell; `cleanup.run` executes them uniformly. Providers are a pure read model (one responsibility: discover).
- **Dropped `__init_subclass__`** — registry uses an explicit import list. Grep-findable, no magic.
- **Added `Prompt` callable alias** — typed `Callable`, not a Protocol (single method, stateless).
- **Specified `Entry.size_bytes` invariant** — always populated by `Provider.discover()`; `discovery.scan` never re-sizes.
- **`Report.to_json` / `from_json` is the single canonical serializer** — used by `--json`, snapshots, and `rendering`. No duplicate serialization path.
- **Added `DiffReport` / `DiffRow`** for `history.diff`.
- **Clarified `rendering` is a presentation layer**, not a bounded context.
