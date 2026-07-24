#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
DB_URL="${DATABASE_URL:-sqlite:///./insurance.db}"
if [[ "$DB_URL" == sqlite* ]] && [[ -z "${UVICORN_WORKERS:-}" ]]; then
  WORKERS=1
else
  WORKERS="${UVICORN_WORKERS:-4}"
fi
echo "Starting API on :8000 with ${WORKERS} workers (set UVICORN_RELOAD=1 for hot reload, single worker)"
if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
fi
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers "$WORKERS"
