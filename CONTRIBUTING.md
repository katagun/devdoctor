# Contributing to DevDoctor

Thanks for helping improve DevDoctor — a local developer-workstation resource
manager for macOS and Linux. This guide covers how to get set up, the checks
your change needs to pass, and the conventions the project follows.

> **Note on names:** the product is **DevDoctor**; the installable Python
> package and CLI are still named `devdoctor` during the transition. You'll see
> both in the tree — that's expected.

## Getting set up

DevDoctor uses [uv](https://docs.astral.sh/uv/) for the Python side and
[Bun](https://bun.com/docs/installation) for the web UI.

```bash
# Python: install the project with dev + web extras into a managed venv
uv sync --extra dev --extra web

# Web UI (optional — only if you touch web/)
cd web && bun ci
```

Run the tool from the source tree:

```bash
uv run devdoctor scan
uv run devdoctor serve          # local web UI
```

## Before you open a pull request

All of these run in CI and must pass. Run them locally first:

```bash
# Python
uv run --extra dev --extra web ruff check src tests      # lint
uv run --extra dev --extra web ruff format src tests      # auto-format
uv run --extra dev --extra web mypy                        # types (strict)
uv run --extra dev --extra web pytest                      # tests

# Web (only if you changed web/)
cd web
bun run typecheck
bun run test
bun run build
bun run test:e2e   # builds, then runs Playwright against a hermetic `devdoctor serve`
```

The end-to-end suite builds a throwaway home under the OS temp directory and
starts the server there, so it never scans your real caches. It needs
`uv sync --extra web` and, once, `bun run playwright install chromium`.

A pre-commit hook config is included; enable it with
`uv run --extra dev pre-commit install` to catch lint/format issues before you
commit.

### Measuring scan time

A scan's time is almost entirely directory sizing, so it grows with every
provider that finds more bytes (#92). Two rules keep it in check:

- Size directories through `devdoctor.sizer`. A provider with several
  directories calls `size_many(paths)` once instead of sizing them in a loop.
  Every walk runs on one shared pool of four: fewer leaves the disk idle, more
  made the same trees slower to size on APFS.
- Measure before and after. `uv run python scripts/bench_sizer.py` compares one
  walk at a time with the pool, on synthetic trees or on directories you name,
  and fails if the totals differ. The script's docstring shows how to rank the
  providers of a real scan by duration.

Sizes are never cached between scans. A directory's modification time does not
change when a file deep inside it does, so no cheap key can prove a cached size
is still right, and accurate sizes are the point of the tool.

## Conventions

- **Presentation observes, never decides.** `cleanup.iter_cleanup_events` is the
  one state machine; the CLI presenter and the web runner only observe its
  events (`on_event`) and answer its prompts. Output code lives in
  `rendering.py`, never in `cleanup.py`.
- **Tests are required** for behavior changes and bug fixes. The suite is the
  contract — a fix without a regression test can silently come back.
- **Match the surrounding code.** Keep comments to constraints and intent the
  code can't express, not narration.
- **Types are strict.** `mypy --strict` runs over `src/`; keep it green.
- **Small, focused commits** with a clear message describing the *why*.

## The safety model (please preserve it)

DevDoctor runs destructive commands, so the safety guarantees are load-bearing.
If your change touches discovery, recipes, or cleanup, keep these intact:

- `clean` defaults to **preview only** — no prompts, no shell calls.
- Entries are labelled **safe / reclaimable / dangerous**; dangerous entries are
  skipped unless the user passes `--allow-dangerous`.
- Commands run as **argv lists, never through a shell**, and paths are quoted.
- `recipe` and the generated script keep every destructive line **commented
  out** and free of injectable content.
- Prefer marking a path **dangerous** over risking user data when a directory
  mixes cache with real data (uploads, chat history, generated output).

## Reporting bugs and requesting features

Use the issue templates: **Issues → New issue → Bug report / Feature request**.
For anything security-sensitive, see [SECURITY.md](SECURITY.md) — please do not
open a public issue for vulnerabilities.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
