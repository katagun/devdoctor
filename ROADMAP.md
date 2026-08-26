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

## Now — in progress / up next

- **Desktop app** — a hardened Electron app so you can double-click to launch,
  no terminal required. The groundwork exists; the remaining work is packaging
  and first-run flows. ([#5](https://github.com/katagun/devdoctor/issues/5))
- **Code-signing & notarization** for the macOS desktop build, so it installs
  cleanly past Gatekeeper. ([#6](https://github.com/katagun/devdoctor/issues/6))
- **Claim the package name on PyPI** so the install path can't be hijacked.
  ([#7](https://github.com/katagun/devdoctor/issues/7))
- **De-flake CI** — make the SSE lifecycle test deterministic and move it off
  deprecated APIs. ([#14](https://github.com/katagun/devdoctor/issues/14))

## Next — planned

- **Faster scans** — parallelize provider discovery and share an inode cache so
  large model/Docker caches don't dominate scan time.
  ([#9](https://github.com/katagun/devdoctor/issues/9))
- **Virtualized tables** — windowed rendering for scans with thousands of
  entries. ([#8](https://github.com/katagun/devdoctor/issues/8))
- **Structured logging & diagnostics** — surface "permission denied" vs
  "nothing to clean" instead of silently swallowing errors.
  ([#10](https://github.com/katagun/devdoctor/issues/10))
- **Release process** — a `CHANGELOG.md` and a lightweight, repeatable release
  flow. (Dependabot, CodeQL, and CI have already landed.)
  ([#15](https://github.com/katagun/devdoctor/issues/15))

## Later — on the radar

- **SQLite migrations** — a real, versioned migration path before the schema
  changes again. ([#11](https://github.com/katagun/devdoctor/issues/11))
- **Cross-provider id safety** — key cleanup selection by `(provider, id)`.
  ([#12](https://github.com/katagun/devdoctor/issues/12))
- **Sharper memory classification** — word-boundary process matching so the
  advisor's per-kind totals are accurate.
  ([#13](https://github.com/katagun/devdoctor/issues/13))

## Principles that won't change

Whatever ships, the safety model stays: preview-first cleanup, explicit
safe/reclaimable/dangerous labels, no shell execution, and no telemetry —
everything runs locally. See the [README](README.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

---

Have a request or found something missing? Open an
[issue](https://github.com/katagun/devdoctor/issues/new/choose).
