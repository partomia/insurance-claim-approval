#!/usr/bin/env bash
# Preflight checks — safe to run anytime, never mutates anything.
# Usage: bash cml/doctor.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

FAILN=0

req() { # req "label" cmd...
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$label"; else err "$label"; FAILN=$((FAILN+1)); fi
}
opt() { # opt "label" cmd...   (missing = warn, not fail)
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$label"; else warn "$label (optional)"; fi
}

log "Tooling"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
req "python3 available"   command -v python3
req "git available"       command -v git
opt "uv available"        command -v uv
opt "npm available"       command -v npm
opt "tesseract-ocr available (needed for evidence OCR)" command -v tesseract
if command -v uv >/dev/null 2>&1; then ok "uv version: $(uv --version)"; fi
if command -v npm >/dev/null 2>&1; then ok "npm version: $(npm --version)"; fi

log "Cloudera AI runtime signals"
if [[ -n "${CDSW_APP_PORT:-}" ]]; then
  ok "CDSW_APP_PORT=$CDSW_APP_PORT (running as an Application)"
else
  warn "CDSW_APP_PORT not set — normal in a plain Session terminal, expected once deployed as an Application"
fi
[[ -n "${CDSW_PROJECT:-}" ]] && ok "CDSW_PROJECT=$CDSW_PROJECT"

log "Project state"
[[ -d "$BACKEND/.venv" ]] && ok "backend/.venv exists" || warn "backend/.venv missing — run 'cml/cli.sh setup'"
[[ -f "$FRONTEND/dist/index.html" ]] && ok "frontend/dist built" || warn "frontend/dist missing — run 'cml/cli.sh setup' (or --skip-frontend for API-only)"

log "backend/.env"
validate_env || FAILN=$((FAILN+1))
check_env_drift

log "Disk"
df -h "$ROOT" 2>/dev/null | tail -1 | awk '{print "  free: "$4" / total: "$2" ("$5" used)"}'

echo
if [[ "$FAILN" -eq 0 ]]; then
  ok "Doctor: no blocking issues"
  exit 0
else
  err "Doctor: $FAILN blocking issue(s) — see above"
  exit 1
fi
