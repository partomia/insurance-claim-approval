#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Cloudera AI (Workbench / CML) one-shot bootstrap.
#
# Prefer running it via the dispatcher:  bash cml/cli.sh setup
# (or directly:                          bash cml/setup.sh)
#
# Idempotent — safe to re-run. Skips expensive steps (uv sync, npm install)
# when their lockfiles haven't changed since the last successful run. It:
#   1. installs `uv` if missing
#   2. creates backend/.env from the template (only if absent)
#   3. installs backend deps into backend/.venv
#   4. tests the DB connection
#   5. seeds demo data + builds the Chroma RAG index
#   6. builds the frontend into frontend/dist (served by FastAPI)
#   7. validates backend/.env and reports what's still missing
#
# Then start the app with:  bash cml/cli.sh start   (or set as the App script)
#
# Flags:
#   --skip-frontend   don't build the SPA (API-only)
#   --skip-seed       don't seed / ingest
#   --reset-db        wipe + recreate DB tables during seed (FORCE_DB_RESET=1)
#   --run             launch the app at the end (blocks)
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
start_logging setup

SKIP_FRONTEND=0
SKIP_SEED=0
RESET_DB=0
RUN_AFTER=0
for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --skip-seed)     SKIP_SEED=1 ;;
    --reset-db)      RESET_DB=1 ;;
    --run)           RUN_AFTER=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

log "Repo root: $ROOT"

# --- 1. ensure uv -----------------------------------------------------------
ensure_uv || exit 1
ensure_net_tools

# --- 2. backend/.env --------------------------------------------------------
if [[ ! -f "$BACKEND/.env" ]]; then
  log "Creating backend/.env from .env.example"
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  env_set CLAIM_PROCESSING_MODE sync
  env_set SERVE_FRONTEND true
  warn "backend/.env created with SQLite + sync defaults."
  warn "Edit it to set your LLM (ENDPOINT/API_KEY or GROQ_API_KEY) and, if needed, DB_BACKEND=impala + IMPALA_* / kinit."
else
  ok "backend/.env already exists — leaving it untouched"
fi

# --- 3. backend deps ---------------------------------------------------------
cd "$BACKEND"
if hash_changed backend_lock uv.lock pyproject.toml; then
  log "Installing backend dependencies (uv sync)"
  uv python install 3.13 >/dev/null 2>&1 || warn "Could not pre-provision Python 3.13 (offline?); relying on runtime interpreter"
  if ! uv sync --frozen; then
    warn "Frozen sync failed (lock/interpreter mismatch) — re-resolving with 'uv sync'"
    uv sync
  fi
  save_hash backend_lock uv.lock pyproject.toml
  ok "Backend environment ready at backend/.venv"
else
  ok "Backend deps unchanged since last successful setup — skipping uv sync"
fi

# --- 4. DB connectivity -----------------------------------------------------
log "Testing DB connection"
if uv run python scripts/test_db_connection.py; then
  ok "DB reachable"
else
  warn "DB connection failed. If DB_BACKEND=impala, run 'kinit' or set IMPALA_USER/PASSWORD (LDAP) in backend/.env, then re-run."
fi

# --- 5. seed + RAG index ----------------------------------------------------
if [[ "$SKIP_SEED" -eq 0 ]]; then
  log "Seeding demo data"
  if [[ "$RESET_DB" -eq 1 ]]; then export FORCE_DB_RESET=1; fi
  uv run python seed.py || warn "Seed step failed — check DB config"
  unset FORCE_DB_RESET || true

  log "Building Chroma RAG index"
  uv run python scripts/ingest_policies.py || warn "RAG ingest failed (non-fatal) — check embeddings/LLM config"
else
  warn "Skipping seed/ingest (--skip-seed)"
fi

# --- 6. frontend build -------------------------------------------------------
if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
  if command -v npm >/dev/null 2>&1; then
    cd "$FRONTEND"
    if hash_changed frontend_lock package-lock.json package.json; then
      log "Installing frontend dependencies"
      if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
      save_hash frontend_lock package-lock.json package.json
    else
      ok "Frontend deps unchanged — skipping npm install"
    fi
    log "Building frontend (same-origin: VITE_API_URL empty)"
    VITE_API_URL="" npm run build
    ok "Frontend built at frontend/dist (FastAPI will serve it)"
  else
    warn "npm not found in this runtime — skipping SPA build. The API will run, but the UI won't be served."
    warn "Use an ML Runtime that includes Node, or deploy the frontend separately (e.g. Vercel)."
  fi
else
  warn "Skipping frontend build (--skip-frontend)"
fi

# --- 7. env validation -------------------------------------------------------
log "Validating backend/.env"
validate_env
check_env_drift

log "Setup complete."
echo "  Start the app:   bash cml/cli.sh start        (= python cml/run.py)"
echo "  Verify it's up:  bash cml/cli.sh smoke"
echo "  Or set the Cloudera AI Application 'Script' to:  cml/run.py"

if [[ "$RUN_AFTER" -eq 1 ]]; then
  log "Launching app (--run)"
  exec python3 "$ROOT/cml/run.py"
fi
