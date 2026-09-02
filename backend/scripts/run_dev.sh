#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
python scripts/test_impala_connection.py
echo "Starting API on :8000 (set UVICORN_RELOAD=1 for hot reload)"
if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
fi
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-4}"
