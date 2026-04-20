# diskdoctor

Repeatable disk-cache analyzer and interactive cleanup for macOS and Linux.

## Install

```bash
uv tool install --from git+https://github.com/<you>/diskdoctor diskdoctor
# or from a local clone:
uv tool install .
```

## Commands

```bash
diskdoctor scan                       # Rich table of all known caches, sorted by size
diskdoctor scan --json                # same, as JSON to stdout
diskdoctor scan --min-size 100M --risk safe,reclaimable

diskdoctor recipe                     # emit a commented-out cleanup shell script
diskdoctor recipe --provider ollama   # only one section
diskdoctor recipe -o /tmp/cleanup.sh  # write to file

diskdoctor clean                      # preview (no prompts, no shell calls)
diskdoctor clean --execute            # interactive cleanup (per-entry prompts + final confirm)
diskdoctor clean --execute --yes-safe
diskdoctor clean --execute --allow-dangerous

diskdoctor snapshot --note "before cleanup"
diskdoctor diff                       # latest two snapshots
diskdoctor diff --to live             # last snapshot vs current

diskdoctor providers                  # show registered providers and their availability
```

## Safety model

- `clean` defaults to **preview only** — zero prompts, zero shell commands.
- `recipe` always emits a **commented-out** script. You review and uncomment what you want.
- Entries are labelled **safe / reclaimable / dangerous**. DANGEROUS entries are *skipped* unless you pass `--allow-dangerous`.

## Design

See [docs/superpowers/specs/2026-04-18-diskdoctor-design.md](docs/superpowers/specs/2026-04-18-diskdoctor-design.md).

## Web UI

```bash
# Install with the web extra
uv tool install '.[web]' --force

# Launch
diskdoctor serve
# → opens http://127.0.0.1:<random-port> in your browser
```

Flags:

- `--port N` — bind a specific port (0 = random free port, default).
- `--no-browser` — do not auto-open the default browser.

Dev loop:

```bash
# Terminal 1: FastAPI
uv run diskdoctor serve --port 8731 --no-browser

# Terminal 2: Vite with HMR (proxies /api to 8731)
cd web && npm run dev
```

Open http://localhost:5173.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run mypy src
```
