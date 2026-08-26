# DevDoctor

[![CI](https://github.com/katagun/devdoctor/actions/workflows/ci.yml/badge.svg)](https://github.com/katagun/devdoctor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

DevDoctor is a local developer workstation resource manager.

Today it includes the original diskdoctor workflow: repeatable disk-cache
analysis and interactive cleanup for macOS and Linux. The current installable
Python package and CLI remain named `diskdoctor` during the transition.

**[See what it does → katagun.github.io/devdoctor](https://katagun.github.io/devdoctor/)**

## Install

```bash
uv tool install --from git+https://github.com/katagun/devdoctor diskdoctor
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
# One-time: install the SPA's node deps
cd web && npm install && cd ..

# Terminal 1: FastAPI
uv run diskdoctor serve --port 8731 --no-browser

# Terminal 2: Vite with HMR (proxies /api to 8731)
cd web && npm run dev
```

Open http://localhost:5173.

For a production-style run, use the deploy helper (hatchling force-includes the
built bundle into the package on release):

```bash
./scripts/deploy.sh                       # install web deps + build + reinstall
./scripts/deploy.sh --skip-npm-install    # skip `npm install` when node_modules is fresh
./scripts/deploy.sh --help                # show what each step does and why
diskdoctor serve
```

The script runs the three steps you otherwise have to remember in order:

```bash
cd web && npm run build && cd ..
uv cache clean diskdoctor  # drop the stale wheel built from an older dist/
uv tool install '.[web]' --force
```

> Gotcha: `uv tool install --force` reuses a cached wheel if the source path
> hasn't changed. If you're running the steps by hand, the `uv cache clean`
> line is the one that's easy to skip — without it you'll keep seeing the
> "assets are not built yet" placeholder. `scripts/deploy.sh` handles this
> for you.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run mypy src
```

## Roadmap

The CLI and web UI ship today; the desktop app and more are on the way. See
[ROADMAP.md](ROADMAP.md) and the [issue tracker](https://github.com/katagun/devdoctor/issues).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup,
the checks CI runs, and the safety conventions to preserve. Bug reports and
feature requests go through **Issues → New issue**.

## Security

DevDoctor runs destructive commands, so please report vulnerabilities privately
rather than in a public issue. See [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
