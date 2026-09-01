#!/usr/bin/env bash
# Rebuild the SPA bundle and reinstall `devdoctor` as a uv tool so
# `devdoctor serve` picks up the fresh frontend assets.
#
# Why these three steps are all needed:
#   1. `npm run build` writes a new JS/CSS bundle under
#      src/devdoctor/web/_static/dist/. hatchling force-includes that path
#      when building the wheel, so the bundle ships inside the installed tool.
#   2. `uv cache clean devdoctor` drops any wheel uv already cached for this
#      source. Without this, `uv tool install --force` happily reuses the
#      stale wheel and you'll keep seeing "assets are not built yet".
#   3. `uv tool install '.[web]' --force` rebuilds the wheel against the
#      updated source tree and swaps the installed tool atomically.
#
# After install, this script also restarts any `devdoctor serve` running
# on the configured port (default 8731) so the new code is actually loaded.
# A running Python process keeps its imports in memory; just reinstalling
# the wheel does not refresh them. Skip with --skip-restart.
#
# Usage: run from anywhere — the script resolves its own repo root.
#   ./scripts/deploy.sh                     # default (restart if running)
#   ./scripts/deploy.sh --skip-npm-install  # skip npm install
#   ./scripts/deploy.sh --skip-restart      # don't touch the running server
#   ./scripts/deploy.sh --port 8080         # check a non-default port

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_NPM_INSTALL=0
SKIP_RESTART=0
PORT=8731

# Parse flags. --port takes a value; everything else is a boolean.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-npm-install) SKIP_NPM_INSTALL=1; shift ;;
    --skip-restart) SKIP_RESTART=1; shift ;;
    --port)
      if [[ $# -lt 2 ]]; then
        echo "error: --port requires a value" >&2
        exit 2
      fi
      PORT="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown flag: $1" >&2
      exit 2
      ;;
  esac
done

for cmd in npm uv; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "error: '$cmd' not on PATH" >&2
    exit 1
  fi
done

if [[ $SKIP_NPM_INSTALL -eq 0 ]]; then
  echo "→ Installing web deps (pass --skip-npm-install to skip)"
  (cd web && npm install --silent)
fi

echo "→ Building SPA bundle"
(cd web && npm run build)

echo "→ Clearing cached devdoctor wheel"
uv cache clean devdoctor

echo "→ Installing devdoctor with web extra"
uv tool install '.[web]' --force

restart_server() {
  local port="$1"

  # Detect a listener. -t prints just PIDs. Empty output = nothing listening.
  local pid
  pid="$(lsof -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)"
  if [[ -z "${pid:-}" ]]; then
    echo "→ No server running on port $port (nothing to restart)"
    return 0
  fi

  # Pull the full cmdline once, use it for both the safety check and replay.
  # `ps -p PID -o args=` is POSIX and works on macOS + Linux.
  local cmdline
  cmdline="$(ps -p "$pid" -o args= 2>/dev/null | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if [[ -z "$cmdline" ]]; then
    echo "⚠ Could not read cmdline for PID $pid — skipping restart"
    return 0
  fi

  # Refuse to touch unrelated processes that happen to own the port.
  if [[ "$cmdline" != *devdoctor* ]]; then
    echo "⚠ Port $port used by non-devdoctor process (PID $pid): $cmdline"
    echo "  leaving it alone"
    return 0
  fi

  echo "→ Restarting server on port $port (PID $pid)"
  echo "  cmdline: $cmdline"

  kill "$pid" 2>/dev/null || true
  # Wait up to 3s for graceful shutdown.
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [[ $waited -ge 3 ]]; then
      echo "  SIGTERM didn't take — sending SIGKILL"
      kill -9 "$pid" 2>/dev/null || true
      sleep 1
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done

  # Wait for the port to actually be released before relaunching, otherwise
  # the new server will EADDRINUSE.
  waited=0
  while lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; do
    if [[ $waited -ge 5 ]]; then
      echo "  port $port still occupied after 5s — aborting auto-restart"
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done

  local log_dir="$HOME/.cache/devdoctor"
  local log="$log_dir/serve.log"
  mkdir -p "$log_dir"

  # Relaunch with the captured cmdline, detached from this shell.
  # setsid + nohup + disown means ctrl-c / this script's exit won't take it
  # down. Output goes to a known log so a crash is diagnosable.
  nohup bash -c "$cmdline" >"$log" 2>&1 </dev/null &
  disown

  echo "  relaunched in background (log: $log)"
}

if [[ $SKIP_RESTART -eq 0 ]]; then
  restart_server "$PORT"
else
  echo "→ Skipping server restart (--skip-restart)"
fi

echo "✓ Done"
