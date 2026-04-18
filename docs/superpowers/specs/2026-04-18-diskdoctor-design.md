# diskdoctor — Design

Date: 2026-04-18
Status: Draft v4 (architectural review)

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
- **Separation of concerns**: three top-level modules (`discovery`, `cleanup`, `history`) covering the three use cases; `rendering` is a presentation layer they all feed into. Consistent domain vocabulary: Entry, Recipe, Risk, Report. (Calling these "bounded contexts" would overstate what's going on — this is a ~1.5k-LoC CLI, not a distributed system.)
- **TDD**: every unit has a failing test written first. The narrow Shell port + real `tmp_path` make this tractable without heavy mocking machinery.

## Architecture

Three use-case modules:

1. **discovery** — orchestrates providers, returns a `Report`. `scan(providers, filters, now) -> Report`. `Provider.discover()` populates `Entry.size_bytes` itself (using the `sizer` helper for path-based entries); `discovery.scan` never re-sizes.
2. **cleanup** — interactive run loop + script emission. `run(report, shell, prompt_choice, confirm, opts) -> list[CleanResult]` and `build_script(report) -> str`.
3. **history** — snapshot JSON files and diffing. `write_snapshot(report, dir) -> Path`, `load_snapshot(path) -> Report`, `diff(before, after) -> DiffReport`.

Supporting modules:

- **rendering** — Rich tables/spinners and interactive prompts. Owns all human-facing output. The real `PromptChoice` and `Confirm` callables are built here.
- **registry** — explicit list of class providers + YAML-backed `PathProvider` construction. `load_providers(shell) -> list[Provider]`. Enforces name-uniqueness (duplicate between class providers and YAML, or within YAML, is a startup error).
- **ports / types / sizer** — infrastructure: the `Shell` port, shared dataclasses, the sizing helper.

`cli.py` is the runtime composition root. It exposes a factory:

```python
def build_cli(shell: Shell | None = None) -> click.Group:
    shell = shell or RealShell()
    providers = registry.load_providers(shell)
    # ... bind providers into each subcommand's context
    return cli
```

`main()` calls `build_cli()` with defaults. Tests call `build_cli(FakeShell(...))` and drive it with Click's `CliRunner` — no env-var hacks, no global singletons.

**Concurrency**: v1 is strictly sequential. Scanning all providers on a heavily-used machine is expected to complete in a couple of seconds; parallelism is a future extension only if measurements justify it.

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
                                           OR  cleanup.run(Report, shell, prompt_choice, confirm, opts) → list[CleanResult]
                                           OR  history.write_snapshot(Report, dir) / history.diff(a, b)
```

## Ports and seams

One port (`Shell`) and two typed callable aliases (`PromptChoice`, `Confirm`). Everything else is passed as plain data or uses the stdlib directly against `tmp_path` in tests.

```python
@dataclass(frozen=True)
class ShellResult:
    returncode: int
    stdout: str
    stderr: str

class Shell(Protocol):
    def run(self, argv: list[str], *, check: bool = False) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...

Choice = Literal["y", "n", "a", "s", "q"]         # per-entry answer
PromptChoice = Callable[[Entry], Choice]           # called once per candidate Entry
Confirm = Callable[[str], bool]                    # final yes/no with a summary message
```

Why so few seams:
- `datetime` — pass as a parameter to `scan`/snapshot code. No Clock Protocol.
- `filesystem` — `pathlib.Path` + `os.walk` work fine; tests use `tmp_path` fixtures (honest trees of real files). A `Filesystem` Protocol would be indirection with no test payoff.
- `PromptChoice` and `Confirm` are stateless single-call functions, so they don't earn a Protocol. `cleanup.run` holds any aggregate state (e.g. "user said 'a' for this provider, don't prompt again").

Real impls live in `ports.py` (`RealShell`) and `rendering.py` (the Rich-backed prompt factory, `real_prompts() -> tuple[PromptChoice, Confirm]`). Test doubles:
- `FakeShell(responses: dict[tuple[str, ...], ShellResult])` — argv-keyed, deterministic.
- Prompt stubs are plain functions; tests commonly use a scripted `list.pop(0)` closure.

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
│   ├── types.py                     Risk, Entry, Report, DiffReport, DiffRow, CleanResult, CleanupOpts, ScanFilters, Choice, PromptChoice, Confirm
│   ├── ports.py                     Shell Protocol; ShellResult; RealShell
│   ├── sizer.py                     size_path(root) -> (bytes, skipped) — symlink-safe, one device
│   ├── registry.py                  explicit class-provider list + YAML loader; load_providers(shell); name-uniqueness check
│   ├── discovery.py                 scan(providers, filters, now) -> Report
│   ├── cleanup.py                   run(report, shell, prompt_choice, confirm, opts); build_script(report)
│   ├── history.py                   write_snapshot, load_snapshot, diff
│   ├── rendering.py                 Rich tables; spinner context; real_prompts() factory
│   ├── data/paths.yaml              declarative entries for simple caches
│   └── providers/
│       ├── __init__.py
│       ├── base.py                  Provider ABC; PathProvider (YAML + glob)
│       ├── ollama.py                daemon-or-walk: prefer `ollama list`, fall back to walking ~/.ollama/models
│       ├── docker.py                `docker system df` parsing; clean via `docker system prune`
│       ├── lm_studio.py             walks ~/.cache/lm-studio/models, groups by publisher/model
│       └── huggingface.py           walks ~/.cache/huggingface/hub, groups by repo, symlink-safe
├── tests/
│   ├── conftest.py                  FakeShell; scripted PromptChoice/Confirm builders; tmp-tree fixtures
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
class ScanFilters:
    min_size_bytes: int = 0
    risks: frozenset[Risk] | None = None          # None = include all
    providers: frozenset[str] | None = None       # None = include all

@dataclass(frozen=True)
class CleanupOpts:
    execute: bool = False                         # False = preview only, no prompts, no execution
    yes_safe: bool = False                        # auto-approve SAFE entries
    allow_dangerous: bool = False                 # required to even prompt for DANGEROUS entries
    providers: frozenset[str] | None = None       # None = all providers

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

`PathProvider` is the workhorse: one instance per YAML entry. `discover()`:
1. Expands `~`/`${HOME}` in each configured `path`, then glob-expands it.
2. For each resolved concrete path that exists, calls `sizer.size_path(path)`.
3. Builds one `Entry` per path with:
   - `label = str(resolved_path)` (absolute path, so multiple globbed entries are distinguishable)
   - `path = resolved_path`
   - `recipe = [yaml_recipe.format(path=shlex.quote(str(resolved_path)))]`
   - `mtime = lstat(resolved_path).st_mtime`

YAML construction is owned by the class itself: `PathProvider.from_yaml(spec: dict, shell: Shell) -> PathProvider`. The registry loads the YAML document into dicts and hands each to this classmethod — so YAML schema and path-provider semantics live together, not scattered.

## Dependencies

Runtime:
- `click` — CLI parsing.
- `rich` — tables, spinners, colored output, interactive prompts.
- `pyyaml` — load `paths.yaml`.
- `huggingface_hub` — **optional**. Imported inside the HF provider with `try: import huggingface_hub`. When present, used to produce prettier labels from repo ids; never used for sizing or cleanup.

Dev:
- `pytest`, `pytest-cov`, `ruff` (lint + format), `mypy` (strict on `src/`), `pre-commit`.

Python 3.12+. Packaged with `hatchling`. Installable via `uv tool install .` or `uvx --from . diskdoctor ...` for zero-install runs during development.

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
- `paths` entries are tilde- and `${HOME}`-expanded, then glob-expanded. One Entry per resolved, existing path.
- `{path}` in `recipe` is interpolated per matched path, shell-quoted with `shlex.quote` (so paths with spaces or quotes cannot inject).
- `recipe` may be a single string (→ one-element list) or a list of strings (multiple shell commands run in sequence, each as a separate `shell.run`).
- Risk and platform strings are validated against the `Risk` enum and the fixed platform set `{"darwin", "linux"}` at load time; malformed YAML is a startup error naming the offending entry.
- `name` must be unique across the combined (class + YAML) provider set — enforced by `registry.load_providers`.

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
diskdoctor scan [--json] [--min-size SIZE] [--risk RISK]... [--provider NAME]...
    Rich table: Name | Label | Size | Risk | Stale? | First recipe line (truncated)
    Sort desc by size; footer totals; a single "Scanning..." spinner while the
    scan runs (no per-provider progress bar).
    --json emits Report.to_json() to stdout; suppresses table rendering.
    --min-size: "500M", "2G", "100K" (base-10) or plain integer bytes.
    --risk: may be repeated OR comma-separated ("--risk safe --risk reclaimable"
        or "--risk safe,reclaimable"); unknown values error out.
        Semantics: INCLUDE only entries whose risk is in the set (default: all).
    --provider: may be repeated; filter to named providers.

diskdoctor recipe [--provider NAME]... [-o FILE]
    Emits a shell script. Every destructive line is COMMENTED OUT by default.
    The user reviews and uncomments the sections they want, then runs it.
    No --executable flag — this is intentional: the tool never emits a ready-
    to-run destructive script. Format per provider:
        # --- <provider>: <human-size> freed, risk=<risk> ---
        # <description>
        # <recipe line 1>
        # <recipe line 2>
    -o writes to file; otherwise stdout.

diskdoctor clean [--provider NAME]... [--execute] [--yes-safe] [--allow-dangerous]
    Default (no --execute): PREVIEW only. Prints the candidate table and a hint
    to re-run with --execute. Zero prompts, zero shell calls.
    With --execute:
      - iterate candidate entries (sorted desc by size, grouped by provider)
      - for each: PromptChoice → Choice in {y, n, a=all-in-provider, s=skip-provider, q=quit}
      - --yes-safe         auto-answers 'y' for SAFE entries (no prompt)
      - --allow-dangerous  required to include DANGEROUS entries at all;
                           without it they're listed in the summary as
                           "skipped: dangerous (pass --allow-dangerous)"
      - after the per-entry pass, Rich summary (count + estimated bytes) →
        Confirm ("Execute this cleanup?"); 'n' aborts, zero shell calls.
      - on confirm: run entry.recipe lines via Shell; one entry's failure does
        not abort the others; print a result table of per-entry status and
        actual freed bytes.

diskdoctor snapshot [--note TEXT]
    Runs a scan, writes ~/.local/share/diskdoctor/snapshots/<ISO8601>.json.
    Schema matches --json output plus note, hostname, platform.

diskdoctor diff [--from SNAPSHOT] [--to SNAPSHOT|live]
    Defaults: latest vs second-latest.
    Rich table: provider | before | after | Δ bytes | Δ %  (green=shrunk, red=grew).
    Per-provider aggregates only — no per-entry detail in v1.

diskdoctor providers
    Lists every registered provider: name, risk, platforms, available?, path exists?
```

Key CLI details:
- **"Recipe hint"** column = the first line of `entry.recipe`, truncated to fit the terminal.
- **PathProvider label** = the matched path (absolute), so rows are unambiguous when a YAML entry has multiple/globbed paths.
- **`--executable` is deliberately omitted.** `recipe` always produces a commented-out, review-required script. If the user wants one-shot cleanup they use `clean --execute`.
- **Name uniqueness**: the registry fails fast if two providers (across class + YAML) share a `name`.

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
- **Duplicate provider names** (YAML vs class, or two YAML entries): fail at `load_providers` with both offending sources in the message. A duplicate must never be silently resolved.
- **SIGINT mid-`shell.run`**: the currently-running subprocess receives SIGINT and completes (or is killed). `cleanup.run` catches `KeyboardInterrupt` from its loop, marks remaining entries as `skipped`, prints the partial summary, and exits `130`.

## Testing (TDD)

Every unit starts with a failing test. Ports keep tests fast and hermetic.

Per-module coverage:
- **sizer** — trees with regular files, symlinks (including loops), permission denied, cross-device; uses real `tmp_path` (faster and more honest than faking FS for this module).
- **registry** — loads YAML, rejects malformed entries with location info; combines YAML providers + class providers; deterministic alphabetical order; fails on duplicate names (both YAML-vs-class and YAML-vs-YAML).
- **PathProvider** — `from_yaml` construction; `~` / `${HOME}` expansion; globbing (single-path and glob-path); `{path}` recipe templating with `shlex.quote`; multi-path entries produce one Entry per resolved path.
- **Provider classes** — each tested with `FakeShell`:
  - ollama: `list` success parsing; `list` failure → walk-dir fallback
  - docker: `system df --format json` parsing; handles missing docker binary
  - lm_studio: per-`publisher/model` entry generation from a `tmp_path` tree
  - huggingface: `hub/models--*` grouping; symlink-safe sizing verified against a constructed blob+snapshot tree
- **discovery.scan** — with a small fake registry, confirms filtering, sorting, and totals.
- **cleanup.run** — preview (no --execute) produces no shell calls and no prompts; execute path with scripted `PromptChoice` + `Confirm` covers y/n/a/s/q per entry, the final confirm, auto-approve-safe, and DANGEROUS gating; failures propagate to `CleanResult.status`.
- **cleanup.build_script** — golden-file style: given a Report, assert exact script text.
- **history** — snapshot JSON round-trip; diff computes Δ correctly including added/removed providers.
- **CLI** — Click `CliRunner` driving `build_cli(shell=FakeShell(...))`, with one happy path and one error path per command. No env-var or monkeypatch hacks; the factory signature is the test seam.

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

## Key design choices (and what was considered)

- **Providers are a pure read model.** Their single responsibility is `discover() -> list[Entry]`. The recipe is fully-formed shell stamped on the Entry at discovery time. Execution is a uniform concern in `cleanup.run`. Earlier drafts had `Provider.clean()` / `Provider.recipe()` methods — both dropped as the Entry already carries everything needed.
- **One port only (`Shell`).** `Clock` and `Filesystem` protocols were considered and dropped: `datetime` is passed as a parameter; filesystem work uses stdlib against real `tmp_path` fixtures. Abstractions with no test payoff.
- **YAML for the 90% case, Python for the 10%.** `PathProvider` + `paths.yaml` handles every cache that is "just a directory" (Homebrew, browsers, Claude VM bundles, etc.). Only 4 class providers: ollama, docker, lm_studio, huggingface — the caches with real logic.
- **Explicit registry imports.** No `__init_subclass__` magic. Providers are grep-findable in `registry.py`.
- **Single canonical JSON via `Report.to_json`/`from_json`.** Used by `--json`, snapshot files, and rendering. No parallel serialization paths.
- **Sequential scan in v1.** Parallelism is a future extension if measurement justifies it.
- **`recipe` never emits an executable script.** All destructive lines are commented out. The user reviews and uncomments. `clean --execute` is the route for one-shot cleanup.
