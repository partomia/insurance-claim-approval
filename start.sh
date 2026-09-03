#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-local}"

if [[ "$MODE" == "docker" ]]; then
  echo "Starting with Docker Compose..."
  cd "$ROOT"
  docker compose up --build
  exit 0
fi

echo "Starting ICN Agents locally..."
echo "  Root: $ROOT"

# --- Backend ---
BACKEND="$ROOT/backend"
cd "$BACKEND"

if [[ ! -f ".env" ]]; then
  echo "No backend/.env found — copying from backend/.env.example"
  cp .env.example .env
fi

if [[ ! -d ".venv" ]]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing backend dependencies..."
pip install -q -e ".[dev]" 2>/dev/null || pip install -q -e .

export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

echo "Testing database connection..."
python scripts/test_db_connection.py
echo "Seeding database..."
python seed.py

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
UVICORN_RELOAD="${UVICORN_RELOAD:-1}"
START_CELERY="${START_CELERY:-0}"

PIDS=()

cleanup() {
  echo ""
  echo "Stopping services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

if [[ "$START_CELERY" == "1" ]]; then
  echo "Starting Celery worker..."
  celery -A tasks.celery_app worker --loglevel=info --concurrency=2 &
  PIDS+=($!)
else
  echo "Skipping Celery (set START_CELERY=1 to enable; use CLAIM_PROCESSING_MODE=sync in backend/.env)"
fi

echo "Starting API on http://127.0.0.1:${BACKEND_PORT} ..."
if [[ "$UVICORN_RELOAD" == "1" ]]; then
  uvicorn main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT" &
else
  uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" --workers "${UVICORN_WORKERS:-1}" &
fi
PIDS+=($!)

# --- Frontend ---
FRONTEND="$ROOT/frontend"
cd "$FRONTEND"

if [[ ! -f ".env" ]]; then
  echo "No frontend/.env found — copying from frontend/.env.example"
  cp .env.example .env
fi

if [[ ! -d "node_modules" ]]; then
  echo "Installing frontend dependencies..."
  npm install
fi

echo "Starting frontend on http://127.0.0.1:${FRONTEND_PORT} ..."
npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" &
PIDS+=($!)

echo ""
echo "=========================================="
echo "  API:      http://127.0.0.1:${BACKEND_PORT}"
echo "  API docs: http://127.0.0.1:${BACKEND_PORT}/docs"
echo "  Frontend: http://127.0.0.1:${FRONTEND_PORT}"
echo "=========================================="
echo "Press Ctrl+C to stop all services."

wait
