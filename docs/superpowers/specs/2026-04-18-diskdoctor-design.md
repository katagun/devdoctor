# diskdoctor — Design

Date: 2026-04-18
Status: Draft

## Purpose

A repeatable, inspectable CLI for analyzing disk usage on macOS and Linux, with a focus on the caches and artifacts that actually consume real space on a developer's machine — model caches, container VMs, package manager caches, browser data, and so on. Produces a human report, a machine-readable JSON report, a reviewable shell script of cleanup commands, and an interactive (dry-run-by-default) cleanup mode. Snapshots enable tracking cache growth over time.

The tool is aimed at the author's own workstation first; design choices favor clarity and safety over full-generality.

## Non-goals

- Not a general filesystem analyzer (no `ncdu` replacement, no interactive TUI tree-walk).
- Not a Windows tool. Paths and providers target Darwin and Linux only.
- Not a background daemon. Every action is explicit, foreground, and idempotent.
- No telemetry, no network calls outside of tools the user already has installed (`docker`, `ollama`, `huggingface-cli`, `brew`).

## Top-level decisions

| Decision | Choice |
|---|---|
| Scope | Report + action recipes + interactive cleanup |
| Provider architecture | Hybrid: Python classes for complex caches, YAML-driven `PathProvider` for simple directories |
| Safety model | Dry-run by default; per-item prompts; final confirm summary; risk-tiered display |
| History | On-demand JSON snapshots in `~/.local/share/diskdoctor/snapshots/` |
| Platforms | macOS + Linux |
| Python / packaging | `uv` + `pyproject.toml`, Python 3.12+, `uv tool install` for global |
| CLI name / repo | `diskdoctor` |
| Recipe output | Per-cache snippets and full script both supported |
| Machine output | `--json` flag on `scan` |

## Architecture

Four layers:

1. **Providers** — one class per cache concern. Contract:
   - `name: str`, `description: str`
   - `platforms: list[str]` — `["darwin", "linux"]`; silently skip on other platforms
   - `risk: Risk` — `SAFE` (regenerable, zero cost), `RECLAIMABLE` (regenerable but costly — models, browsers cached for perf), `DANGEROUS` (holds real state; app workspaces, logs with forensic value)
   - `available() -> bool` — dependencies are installed / path exists
   - `discover() -> list[Entry]` — enumerate candidate items (one or many per provider)
   - `recipe(entry) -> list[str]` — the shell commands that would clean it
   - `clean(entry, dry_run: bool) -> CleanResult` — default implementation shells out to `recipe`; complex providers override

2. **Registry** — `load_providers()` returns every built-in `Provider` subclass plus a collection of `PathProvider` instances built from `diskdoctor/data/paths.yaml`. Subclasses self-register at import time via `__init_subclass__`; `load_providers()` sorts the combined list alphabetically by `name` before returning so iteration order is deterministic.

3. **Core** — orchestration without rendering. `scan(registry, filters) -> Report` iterates providers, calls `discover()`, sizes each `Entry` (symlink-safe, stays on one device), and returns a `Report` dataclass. Sizing uses `os.walk(..., followlinks=False)` and skips entries whose device id (`st_dev`) differs from the entry root — prevents accidentally counting external volumes or network mounts.

4. **CLI** — Click command group. Each command is a thin adapter: parse args → call core → render via `render.py` (Rich) or serialize to JSON.

### Data flow

```
CLI command
  ↓ parse args
Core (scan / clean / recipe / snapshot / diff)
  ↓ iterate
Providers.discover() → Entry objects
  ↓ size
Sizer (os.walk, lstat, device check)
  ↓
Report dataclass
  ↓
Render: Rich tables and prompts  OR  JSON serializer
```

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
│   ├── cli.py                       Click group and commands
│   ├── core.py                      scan(), Report orchestration
│   ├── registry.py                  load_providers()
│   ├── types.py                     Risk, Entry, Report, CleanResult dataclasses
│   ├── sizer.py                     du_bytes(), human(), staleness()
│   ├── render.py                    Rich tables, progress bars, prompts
│   ├── recipes.py                   shell script builder with headers and comments
│   ├── data/
│   │   └── paths.yaml               declarative entries
│   └── providers/
│       ├── __init__.py
│       ├── base.py                  Provider ABC and PathProvider
│       ├── ollama.py
│       ├── docker.py
│       ├── huggingface.py
│       ├── lm_studio.py
│       ├── homebrew.py
│       ├── browser.py               Firefox, Chrome, Arc caches
│       └── claude_vm.py             ~/Library/Application Support/Claude/vm_bundles
├── tests/
│   ├── conftest.py
│   ├── test_sizer.py
│   ├── test_registry.py
│   ├── test_providers_path.py
│   ├── test_providers_ollama.py
│   └── test_cli.py
└── docs/superpowers/specs/
    └── 2026-04-18-diskdoctor-design.md
```

`src/` layout prevents accidental imports from the working directory during tests.

### Types

```python
class Risk(str, Enum):
    SAFE = "safe"
    RECLAIMABLE = "reclaimable"
    DANGEROUS = "dangerous"

@dataclass(frozen=True)
class Entry:
    provider: str            # e.g. "ollama"
    id: str                  # provider-scoped unique id (e.g. model tag)
    path: Path | None        # None for logical-only entries (e.g. a docker image)
    label: str               # human description shown in tables
    size_bytes: int
    mtime: float | None      # last-modified epoch for staleness hints
    risk: Risk
    recipe: list[str]        # shell commands to clean this entry

@dataclass
class Report:
    entries: list[Entry]
    scanned_at: datetime
    hostname: str
    platform: str            # "darwin" | "linux"
    note: str | None = None
    # helpers: by_provider(), total_bytes(), filter_by_risk(), to_json()

@dataclass
class CleanResult:
    entry_id: str
    status: Literal["ok", "skipped", "error", "dry_run"]
    freed_bytes: int
    message: str | None = None
```

### Provider contract

```python
class Provider(ABC):
    name: str
    description: str
    platforms: list[str]
    risk: Risk

    def available(self) -> bool: ...
    @abstractmethod
    def discover(self) -> list[Entry]: ...
    def recipe(self, entry: Entry) -> list[str]:
        return list(entry.recipe)
    def clean(self, entry: Entry, dry_run: bool) -> CleanResult:
        # default: subprocess.run each recipe line unless dry_run
        ...
```

`PathProvider` is a concrete `Provider` that reads a YAML entry and maps it to `discover()` returning one `Entry` per configured path.

### `paths.yaml` schema

```yaml
- name: lm-studio-models
  description: LM Studio downloaded models
  risk: reclaimable
  platforms: [darwin, linux]
  paths:
    - ~/.cache/lm-studio/models
  recipe: "rm -rf {path}"

- name: uv-cache
  description: uv package cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/uv
  recipe: "uv cache clean"
```

`{path}` is interpolated per matched path. Tilde expansion and `${HOME}` are handled by the loader.

## CLI surface

```
diskdoctor scan [--json] [--min-size SIZE] [--risk safe,reclaimable,dangerous]
    Rich table: Name | Path | Size | Risk | Stale? | Recipe hint
    Sort desc by size; footer totals; progress bar during sizing.
    --json suppresses rendering, emits Report schema to stdout.
    SIZE syntax: "500M", "2G", "100K" (base-10 suffixes). Plain integers = bytes.
    --risk accepts a comma-separated list; unknown values are a user error.

diskdoctor recipe [NAME...] [-o FILE] [--executable]
    No args    → full script to stdout, header comment, all providers, commented sections.
    With names → only those providers' sections.
    -o         → write to file.
    --executable → emit uncommented destructive lines (default: commented out).

diskdoctor clean [NAME...] [--execute] [--yes-safe] [--allow-dangerous]
    Default is a DRY RUN. Prints what would happen and a hint to re-run with --execute.
    With --execute:
      - per-entry prompt: [y/N/a=all-in-provider/s=skip-provider/q=quit]
      - --yes-safe         auto-approves SAFE entries
      - --allow-dangerous  required to even prompt for DANGEROUS entries
      - after walking entries, show Rich summary (count, est bytes) → final y/N
      - execute; print result table of freed bytes and failures

diskdoctor snapshot [--note TEXT]
    Runs a scan, writes ~/.local/share/diskdoctor/snapshots/<ISO8601>.json
    Schema matches --json output plus note, hostname, platform.

diskdoctor diff [--from SNAPSHOT] [--to SNAPSHOT|live]
    Defaults: latest vs second-latest.
    Rich table: provider | before | after | Δ bytes | Δ % (green=shrunk, red=grew)

diskdoctor providers
    Lists every registered provider: name, risk, platforms, available?, path exists?
```

Exit codes:
- `0` — success (including no-op dry run)
- `1` — user error (bad args, unknown provider)
- `2` — scan or clean completed with some per-entry failures
- `130` — interrupted (SIGINT)

## Error handling

- **Missing external CLI** (no `ollama`, `docker`, `huggingface-cli` on PATH): provider marks itself unavailable; `scan` skips it with a one-line note; no exception escapes to the user.
- **Permission denied while sizing**: counted in a `skipped_paths` field of the entry and logged once in the footer; never fatal.
- **Symlinks and cross-device paths**: `os.walk(followlinks=False)`; `os.lstat` check on `st_dev` compared to the entry root's device; different device → skip that subtree.
- **Clean failures**: one entry's failure does not abort the run. Result table shows per-entry status; exit code becomes `2`.
- **SIGINT during interactive clean**: cancel remaining prompts; print "nothing executed" if the final confirm has not yet been given; otherwise print partial-execution summary.
- **Malformed `paths.yaml`**: fail loudly at startup with the offending entry and schema error. Validation is done with plain dataclasses + explicit checks — no Pydantic dependency — since the schema is small and fixed.

## Testing

- `pytest` with `CliRunner` for CLI tests.
- Each provider has unit tests with `subprocess.run` mocked — no real `ollama` or `docker` invocations from tests.
- `PathProvider` is tested against `tmp_path` fixtures that simulate real cache trees.
- Sizer is tested against constructed trees including symlinks and (where possible) a cross-device mount simulation via `os.stat` monkeypatch.
- Snapshot round-trip test: write report to JSON, reload, verify equality.
- CLI tests cover the happy path and one error path per command.
- Coverage target: core + providers ≥ 80%; CLI lower bar.

## Out of scope for v1

- Remote-host scanning (SSH).
- Scheduled background runs (cron is fine; we won't ship a launchd plist).
- GUI.
- Third-party provider plugin discovery (would be a ten-line addition via `importlib.metadata` if demanded).
- Auto-upload of snapshots anywhere.

## Future extensions

- `diskdoctor watch <cache>` — print a growth alert when a cache crosses a threshold.
- Grafana exporter for snapshot JSON.
- `--parallel` sizing with a thread pool (only if sizing becomes a bottleneck; a cold scan of all caches on the author's machine is expected to finish in seconds).
- Homebrew tap or `uv tool install --from git+...` publication path.
