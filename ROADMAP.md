# DevDoctor Roadmap

DevDoctor is pre-1.0. The **CLI and local web UI ship today**; this roadmap
tracks what's next. It's a snapshot of intent, not a commitment to dates — the
living backlog lives in [GitHub Issues](https://github.com/katagun/devdoctor/issues).

## Recently shipped

- **Public launch** — renamed to `devdoctor`, MIT-licensed, a public
  [landing page](https://katagun.github.io/devdoctor/), and community docs
  (CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue/PR templates).
- **Security & architecture review** — fixed a snapshot path traversal,
  command injection into the generated cleanup script, terminal-escape
  injection via filenames, a stale-PID kill, and several data-loss mislabels;
  hardened the cleanup and memory paths.
- **CI & repo hardening** — GitHub Actions CI (Python + web), CodeQL,
  Dependabot, web ESLint, CODEOWNERS, and SHA-pinned actions.
- **Reliable CI** — the SSE lifecycle test is now deterministic (runs on a
  pre-bound socket, no port race) and off the deprecated websockets stack.
  ([#14](https://github.com/katagun/devdoctor/issues/14))
- **Structured logging & diagnostics** — a `-v/--verbose` flag, no more
  silently-swallowed errors, and scans surface skipped paths (e.g. permission
  denied) instead of looking empty.
  ([#10](https://github.com/katagun/devdoctor/issues/10))
- **Faster scans** — provider discovery now runs concurrently in a bounded
  thread pool, with identical, deterministic output.
  ([#9](https://github.com/katagun/devdoctor/issues/9))
- **Virtualized tables** — CacheTable windows its rows, so scans with thousands
  of entries render only the visible slice.
  ([#8](https://github.com/katagun/devdoctor/issues/8))
- **SQLite migrations** — a real, versioned migration runner so the schema can
  evolve without breaking existing databases.
  ([#11](https://github.com/katagun/devdoctor/issues/11))
- **Cross-provider id safety** — entry ids are namespaced per provider, so
  cleanup selection can't mis-route between providers.
  ([#12](https://github.com/katagun/devdoctor/issues/12))
- **Modern web toolchain** — upgraded to Vite 8 and Vitest 4.

## Now — in progress / up next

- **Desktop app** — a hardened Electron app so you can double-click to launch,
  no terminal required. The groundwork exists; the remaining work is packaging
  and first-run flows. ([#5](https://github.com/katagun/devdoctor/issues/5))
- **Code-signing & notarization** for the macOS desktop build, so it installs
  cleanly past Gatekeeper. ([#6](https://github.com/katagun/devdoctor/issues/6))
- **Claim the package name on PyPI** so the install path can't be hijacked.
  ([#7](https://github.com/katagun/devdoctor/issues/7))

## Next — planned

- **Release process** — a `CHANGELOG.md` and a lightweight, repeatable release
  flow. (Dependabot, CodeQL, and CI have already landed.)
  ([#15](https://github.com/katagun/devdoctor/issues/15))
- **Sharper memory classification** — word-boundary process matching so the
  advisor's per-kind totals are accurate.
  ([#13](https://github.com/katagun/devdoctor/issues/13))

## Later — on the radar

- **Shared inode cache** — dedupe bytes across providers that walk overlapping
  trees (deferred from [#9](https://github.com/katagun/devdoctor/issues/9)
  because it changes reported per-provider totals).

## Principles that won't change

Whatever ships, the safety model stays: preview-first cleanup, explicit
safe/reclaimable/dangerous labels, no shell execution, and no telemetry —
everything runs locally. See the [README](README.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

---

Have a request or found something missing? Open an
[issue](https://github.com/katagun/devdoctor/issues/new/choose).
