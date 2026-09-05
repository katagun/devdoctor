---
name: devdoctor-desktop
description: Use when someone wants to build, install, or launch the DevDoctor Electron desktop app on macOS from a dev checkout — packaging the app, optionally copying it into /Applications, and running it. macOS only; needs the full toolchain (uv, node, PyInstaller). For running the CLI scan/report instead, use the `devdoctor` skill.
---

# DevDoctor desktop — build, install, launch (macOS)

Builds the Electron desktop app, which bundles the web UI plus a standalone
(PyInstaller) copy of the `devdoctor` backend, so it runs with no separate
Python install. **macOS only**, and requires a dev checkout with the toolchain
(`uv`, Bun, Node 20, and PyInstaller via the `dev` extra).

The result is **unsigned** (ad-hoc). That's fine to run locally; a
signed/notarized `.dmg` for distribution is separate (issue #6, needs an Apple
Developer cert). Installing an unsigned app into `/Applications` is a dev
convenience — confirm the user wants it before doing it.

## Build

From the repo root, on the branch/commit you want to package:

```bash
cd web
bun ci
CSC_IDENTITY_AUTO_DISCOVERY=false bun run electron:pack
```

`electron:pack` runs the whole pipeline: build the SPA → build the backend
(`bun run backend:build`, PyInstaller onefile) → verify the bundle
(`node electron/check-backend-bundle.mjs`) → `electron-builder --dir`.
`CSC_IDENTITY_AUTO_DISCOVERY=false` keeps electron-builder from trying to sign.

Output: `web/release/mac-arm64/DevDoctor.app` (Apple Silicon; `web/release/mac/`
on Intel), with the backend embedded at
`Contents/Resources/backend/devdoctor`. Expect a few minutes (bun ci + Vite
build + PyInstaller + an Electron download). The `.app` is ~350 MB.

## Launch (in place)

```bash
open web/release/mac-arm64/DevDoctor.app
```

## Install into /Applications (optional, ask first)

```bash
rm -rf /Applications/DevDoctor.app           # replace any older copy
cp -R web/release/mac-arm64/DevDoctor.app /Applications/
open -a DevDoctor
```

Now it's in Launchpad/Spotlight. The bundle is self-contained (backend lives
inside it), so it runs from `/Applications` independent of the build checkout.
A locally-built bundle has no quarantine attribute, so Gatekeeper won't block it.

## Verify it started

On launch the app spawns the bundled backend and health-checks it. Confirm from
its log (the `DevDoctor` folder name confirms the `app.setName` fix):

```bash
tail -n 20 "$HOME/Library/Application Support/DevDoctor/logs/devdoctor-electron.log"
pgrep -fl "DevDoctor.app/Contents/MacOS/DevDoctor"
```

A healthy log shows `backendCommand=...backend/devdoctor serve --port <N>`,
`Uvicorn running`, and `GET /api/health ... 200 OK`, followed by the SPA and
`/api/*` calls returning 200.

## Notes

- If `bun ci` reports blocked install scripts, inspect them with
  `bun pm untrusted` before deciding whether to trust them.
- To rebuild after code changes, re-run `bun run electron:pack`; then re-copy to
  `/Applications` if you installed it there.
- Don't commit build artifacts (`web/release/`, `web/dist-backend/*`, `.build/`,
  the regenerated `web/_static/dist/index.html`) — they're gitignored.
