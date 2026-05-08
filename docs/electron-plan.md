# DevDoctor Electron Plan

## Goal

Ship DevDoctor as a desktop shell without rewriting the existing web app or
Python backend.

## Milestone 1: Dev Shell

`npm run electron:dev` starts the existing Python/FastAPI backend on a random
localhost port, waits for `/api/health`, opens a native Electron window, and
terminates the backend when the app exits.

This keeps the current same-origin API contract intact: the renderer loads the
backend-served SPA over `http://127.0.0.1:<port>`, so existing `/api/*` calls do
not need an Electron-specific base URL.

## Current Architecture

- Electron main process owns backend lifecycle.
- Backend command in development:
  `uv run diskdoctor serve --port <port> --no-browser`
- Renderer has `nodeIntegration: false`, `contextIsolation: true`, and
  `sandbox: true`.
- External windows are denied and opened through the OS browser.

## Next Packaging Milestones

1. Build a standalone backend executable for macOS.
2. Place it at `web/dist-backend/diskdoctor`.
3. Run `npm run electron:pack` from `web/` to create an unpacked Electron app.
4. Add Full Disk Access guidance for macOS.
5. Add signing, notarization, and release automation.

The Electron launcher already switches backend command by mode:

- Development: `uv run diskdoctor serve --port <port> --no-browser`
- Packaged app: `<resources>/backend/diskdoctor serve --port <port> --no-browser`

Packaging currently assumes the backend executable exists at
`web/dist-backend/diskdoctor`. The pack script checks this precondition before
calling `electron-builder`, so it fails early instead of producing an app that
cannot start. The next backend-specific task is to choose and wire the
executable builder, likely PyInstaller or Nuitka.
