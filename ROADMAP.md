# DevDoctor Roadmap

DevDoctor is pre-1.0. The **CLI and local web UI ship today**; this roadmap
tracks what's next. It's a snapshot of intent, not a commitment to dates — the
living backlog lives in [GitHub Issues](https://github.com/katagun/devdoctor/issues).

## Recently shipped

- **Colima** — `colima-vm-disk` reports Lima disk images against what they
  reserve and gives `colima stop` / `colima delete` guidance instead of a raw
  delete; `colima-cache` offers the downloaded base images.
  ([#85](https://github.com/katagun/devdoctor/issues/85))
- **The web Disk page filters by age and states its coverage** — "untouched
  for" chips are the web form of `scan --older-than`, and the totals row says
  how much of the volume an unfiltered scan accounts for.
- **`uv cache clean` no longer hangs under `uv run`** — the parent uv process
  holds the cache lock; the provider detects it and forces past it.
  ([#127](https://github.com/katagun/devdoctor/issues/127))
- **Coverage** — every unfiltered scan says how much of the volume's used space
  it accounts for, and `scan --coverage` lists the largest directories no
  provider claims. ([#81](https://github.com/katagun/devdoctor/issues/81))
- **Sparse images** — a VM disk such as `Docker.raw` is reported by what it
  occupies, with a note on what it reserves; the gap is never offered as
  reclaimable. ([#86](https://github.com/katagun/devdoctor/issues/86))
- **Age** — `--older-than` on `scan` and `clean`, and `scan --sort age`; an
  entry is as young as the youngest thing it would delete.
  ([#89](https://github.com/katagun/devdoctor/issues/89))
- **Faster scans** — sizing walks a few trees at a time on one shared pool,
  `--provider` decides what runs, and a wedged Docker daemon cannot hang a
  scan. Reference machine: 160 s to 51 s.
  ([#92](https://github.com/katagun/devdoctor/issues/92))
- **Time Machine local snapshots** — one all-but-newest bundle plus
  per-snapshot entries, with a generic `covers` rule for bundles.
  ([#124](https://github.com/katagun/devdoctor/issues/124))
- **Docs and the agent contract** — a tutorial, CLI and web references, the
  safety model, an FAQ, and `llms.txt` / `llms-full.txt` for agents.
  ([#125](https://github.com/katagun/devdoctor/issues/125))
- **`clean --execute` shows its plan** — itemised plan, per-entry results
  with the failing command's error, a measured summary, and a `history` log
  shared with the web UI. ([#126](https://github.com/katagun/devdoctor/issues/126))
- **Git worktrees** — finds the worktrees agents leave behind, proves which
  are integrated and clean, and offers only those for removal.
  ([#79](https://github.com/katagun/devdoctor/issues/79))
- **Provider architecture** — explicit footprint / reclaimable / shared bytes,
  typed cleanup actions, stable provider IDs and families, deterministic
  hard-link accounting; then JavaScript, Go and Rust, Xcode and Android, and
  Conda / NuGet / tox providers on top of it.
  ([#69](https://github.com/katagun/devdoctor/issues/69)–[#76](https://github.com/katagun/devdoctor/issues/76))
- **Public launch, security review, CI hardening** — renamed to `devdoctor`,
  MIT-licensed, a [landing page](https://sysaidmin.com/), fixes for a snapshot
  path traversal and command injection into the recipe script, and SHA-pinned
  Actions with CodeQL and Dependabot.

## Next — what a coverage scan still misses

Every unfiltered scan now says what share of the disk it accounts for; the
items below are the largest gaps a coverage scan reports, in the order the
numbers suggest.

1. **AI agent and IDE footprint** — Cursor, Codex, OpenCode, Windsurf, exo,
   editor extensions: tens of gigabytes with little coverage today.
   ([#83](https://github.com/katagun/devdoctor/issues/83))
2. **Agent session stores with age-based retention** — transcripts are the
   user's history, not a cache, so the primitive is "sessions older than N
   days", never a blanket delete.
   ([#84](https://github.com/katagun/devdoctor/issues/84))
3. **Remaining developer caches** — rustup toolchains, nvm versions, pyenv,
   pre-commit, puppeteer, vagrant boxes, steampipe.
   ([#88](https://github.com/katagun/devdoctor/issues/88))
4. **Terraform** — `.terraform/providers` duplicated across workspaces; the
   fix is `TF_PLUGIN_CACHE_DIR` advice, not deletion.
   ([#82](https://github.com/katagun/devdoctor/issues/82))
5. **Duplicate files** — advice only, and honestly small: hundreds of
   megabytes, not gigabytes, on the machine that was measured.
   ([#90](https://github.com/katagun/devdoctor/issues/90))

## Release work

- **Code-signing & notarization** for the macOS desktop build, so it installs
  cleanly past Gatekeeper. ([#6](https://github.com/katagun/devdoctor/issues/6))
- **Claim the package name on PyPI** so the install path can't be hijacked.
  ([#7](https://github.com/katagun/devdoctor/issues/7))

## Principles that won't change

Whatever ships, the safety model stays: preview-first cleanup, explicit
safe/reclaimable/dangerous labels, no shell execution, and no telemetry —
everything runs locally. See the [README](README.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

---

Have a request or found something missing? Open an
[issue](https://github.com/katagun/devdoctor/issues/new/choose).
