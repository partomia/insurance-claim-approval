#!/usr/bin/env bash
# Post-deploy smoke test — hits the running app's key endpoints.
# Usage: bash cml/smoke.sh [base-url]
#   With no base-url: uses $CDSW_APP_PORT if set, else the port
#   `cml/cli.sh start`/`restart` actually bound (recorded in
#   cml/.state/app.port — relevant because it may have auto-picked an
#   alternate port; see pick_app_port() in lib.sh), else 8090.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [[ -n "${1:-}" ]]; then
  BASE="$1"
else
  port="${CDSW_APP_PORT:-}"
  [[ -z "$port" && -f "$STATE_DIR/app.port" ]] && port="$(cat "$STATE_DIR/app.port" 2>/dev/null)"
  BASE="http://127.0.0.1:${port:-8090}"
fi
log "Smoke-testing $BASE"

FAILN=0
hit() {
  local path="$1" url body
  url="$BASE$path"
  if body="$(curl -fsS --max-time 10 "$url" 2>&1)"; then
    ok "GET $path -> ${body:0:160}"
  else
    err "GET $path -> FAILED"
    FAILN=$((FAILN+1))
  fi
}

hit "/health"
hit "/api/health"
hit "/api/version"
hit "/api/llm/health"

if curl -fsS --max-time 10 "$BASE/" 2>/dev/null | grep -qi "<html"; then
  ok "GET / -> SPA index served"
else
  warn "GET / -> not an HTML page (API-only mode, or frontend/dist not built)"
fi

echo
if [[ "$FAILN" -eq 0 ]]; then
  ok "Smoke test passed"
else
  err "Smoke test: $FAILN endpoint(s) failed"
  exit 1
fi
