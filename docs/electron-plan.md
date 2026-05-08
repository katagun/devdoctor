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
2. Bundle that executable into the Electron app.
3. Teach Electron to use the bundled backend in packaged mode and `uv run` in
   development.
4. Persist window size and add app menus/log access.
5. Add Full Disk Access guidance for macOS.
6. Add signing, notarization, and release automation.
