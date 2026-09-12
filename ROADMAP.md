# DevDoctor Roadmap

DevDoctor is pre-1.0. The **CLI and local web UI ship today**; this roadmap
tracks what's next. It's a snapshot of intent, not a commitment to dates — the
living backlog lives in [GitHub Issues](https://github.com/katagun/devdoctor/issues).

## Recently shipped

- **Public launch** — renamed to `devdoctor`, MIT-licensed, a public
  [landing page](https://sysaidmin.com/), and community docs
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

## Now — provider architecture

Provider growth needs a clearer contract for measurement, cleanup, identity,
and shared storage before the catalog expands further. These changes are
ordered so each remains backward-compatible with existing snapshots and
stored databases.

1. **Explicit disk byte semantics** — distinguish filesystem footprint,
   estimated reclaimable space, and shared allocations; stop presenting an
   estimate as verified bytes freed.
   ([#69](https://github.com/katagun/devdoctor/issues/69))
2. **Typed cleanup actions** — replace shell-like recipe strings with structured
   path deletion, argv command, and non-executable advice actions while keeping
   generated recipe scripts and old snapshots compatible.
   ([#70](https://github.com/katagun/devdoctor/issues/70))
3. **Provider identity and families** — give atomic providers stable IDs and
   group them into ecosystems without weakening per-provider filtering,
   diagnostics, or failure isolation.
   ([#71](https://github.com/katagun/devdoctor/issues/71))
4. **Deterministic shared-file accounting** — reconcile hard-linked files
   across concurrently scanned entries/providers and expose shared bytes
   without assigning ownership based on thread completion order.
   ([#72](https://github.com/katagun/devdoctor/issues/72))

## Next — provider coverage

- **JavaScript** — npm, pnpm, Yarn, and Bun caches/stores, followed by bounded
  project dependency discovery once shared-file accounting lands.
  ([#73](https://github.com/katagun/devdoctor/issues/73))
- **Go and Rust** — tool-discovered Go caches plus Cargo dependency caches and
  workspace build artifacts.
  ([#74](https://github.com/katagun/devdoctor/issues/74))
- **Xcode/iOS and Android** — derived/build artifacts and tool-managed
  SDK/simulator/emulator storage, with archives and user data kept
  dangerous/advice-only.
  ([#75](https://github.com/katagun/devdoctor/issues/75))
- **Secondary ecosystems** — Conda packages/environments, NuGet/.NET caches,
  and tox/nox environments, with conservative treatment around installed
  environments.
  ([#76](https://github.com/katagun/devdoctor/issues/76))

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
