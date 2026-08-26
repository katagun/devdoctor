# Contributing to DevDoctor

Thanks for helping improve DevDoctor — a local developer-workstation resource
manager for macOS and Linux. This guide covers how to get set up, the checks
your change needs to pass, and the conventions the project follows.

> **Note on names:** the product is **DevDoctor**; the installable Python
> package and CLI are still named `diskdoctor` during the transition. You'll see
> both in the tree — that's expected.

## Getting set up

DevDoctor uses [uv](https://docs.astral.sh/uv/) for the Python side and npm for
the web UI.

```bash
# Python: install the project with dev + web extras into a managed venv
uv sync --extra dev --extra web

# Web UI (optional — only if you touch web/)
cd web && npm ci
```

Run the tool from the source tree:

```bash
uv run diskdoctor scan
uv run diskdoctor serve          # local web UI
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
npm run typecheck
npm run test
npm run build
```

A pre-commit hook config is included; enable it with
`uv run --extra dev pre-commit install` to catch lint/format issues before you
commit.

## Conventions

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
