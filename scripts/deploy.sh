#!/usr/bin/env bash
# Rebuild the SPA bundle and reinstall `diskdoctor` as a uv tool so
# `diskdoctor serve` picks up the fresh frontend assets.
#
# Why these three steps are all needed:
#   1. `npm run build` writes a new JS/CSS bundle under
#      src/diskdoctor/web/_static/dist/. hatchling force-includes that path
#      when building the wheel, so the bundle ships inside the installed tool.
#   2. `uv cache clean diskdoctor` drops any wheel uv already cached for this
#      source. Without this, `uv tool install --force` happily reuses the
#      stale wheel and you'll keep seeing "assets are not built yet".
#   3. `uv tool install '.[web]' --force` rebuilds the wheel against the
#      updated source tree and swaps the installed tool atomically.
#
# Usage: run from anywhere — the script resolves its own repo root.
#   ./scripts/deploy.sh          # default
#   ./scripts/deploy.sh --skip-npm-install  # when node_modules is already fresh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_NPM_INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --skip-npm-install) SKIP_NPM_INSTALL=1 ;;
    -h|--help)
      sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown flag: $arg" >&2
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

echo "→ Clearing cached diskdoctor wheel"
uv cache clean diskdoctor

echo "→ Installing diskdoctor with web extra"
uv tool install '.[web]' --force

echo "✓ Done — restart any running \`diskdoctor serve\` to pick up changes"
