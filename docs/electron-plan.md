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

## Packaging Workflow

`npm run electron:pack` from `web/` now builds the renderer, builds the
standalone Python backend executable, checks the backend bundle contract, and
then creates an unpacked Electron app.

The backend builder uses PyInstaller and writes the executable to
`web/dist-backend/diskdoctor`. That file is intentionally ignored by git because
it is a generated platform-specific artifact.

## Next Packaging Milestones

1. Run and smoke-test the unpacked Electron app from `web/release/`.
2. Add a real app icon.
3. Add signing, notarization, and release automation.
4. Add release CI once signing assets exist.

## macOS Permissions

The Electron Help menu includes a Full Disk Access item. It explains why disk
scans can miss protected folders and opens the macOS Privacy & Security > Full
Disk Access settings pane.

The Electron launcher already switches backend command by mode:

- Development: `uv run diskdoctor serve --port <port> --no-browser`
- Packaged app: `<resources>/backend/diskdoctor serve --port <port> --no-browser`

Packaging assumes the backend executable exists at
`web/dist-backend/diskdoctor`. The pack script builds and then checks this
precondition before calling `electron-builder`, so failures happen before an app
bundle is produced.
