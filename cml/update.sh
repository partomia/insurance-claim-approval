#!/usr/bin/env bash
# Incremental update — pull latest git, reinstall only what actually changed,
# re-verify DB schema. Much faster than a full `setup.sh` re-run.
# Usage: bash cml/update.sh [--no-pull]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
start_logging update
ensure_uv || exit 1

NO_PULL=0
for arg in "$@"; do [[ "$arg" == "--no-pull" ]] && NO_PULL=1; done

if [[ "$NO_PULL" -eq 0 ]]; then
  log "git pull --ff-only"
  git -C "$ROOT" pull --ff-only || warn "git pull failed (local changes / diverged) — resolve manually, then re-run"
else
  warn "Skipping git pull (--no-pull)"
fi

cd "$BACKEND"
if hash_changed backend_lock uv.lock pyproject.toml; then
  log "Backend deps changed — uv sync"
  uv sync --frozen || uv sync
  save_hash backend_lock uv.lock pyproject.toml
else
  ok "Backend deps unchanged — skipping uv sync"
fi

log "Re-checking DB schema (safe, additive only)"
uv run python -c "from db_init import ensure_schema; ensure_schema()"

ensure_node || true
if command -v npm >/dev/null 2>&1; then
  cd "$FRONTEND"
  if hash_changed frontend_lock package-lock.json package.json; then
    log "Frontend deps changed — npm ci + rebuild"
    if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
    VITE_API_URL="" npm run build
    save_hash frontend_lock package-lock.json package.json
  else
    log "Frontend deps unchanged — rebuilding SPA anyway (source may have changed)"
    VITE_API_URL="" npm run build
  fi
else
  warn "npm not found — skipping frontend rebuild"
fi

check_env_drift

log "Update complete."
echo "  Restart the Application (or re-run: python cml/run.py) to pick up changes."
