#!/usr/bin/env bash
# Bundle doctor + app status + port check + recent logs into one file —
# handy to paste when asking for help instead of copy-pasting five commands.
# Usage: bash cml/diagnose.sh [port]
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

PORT="${1:-${CDSW_APP_PORT:-8090}}"
OUT="$LOG_DIR/diagnose-$(date +%Y%m%d-%H%M%S).log"

{
  echo "=== doctor ==="
  bash "$SCRIPT_DIR/doctor.sh"
  echo
  echo "=== app status ==="
  bash "$SCRIPT_DIR/appctl.sh" status
  echo
  echo "=== portcheck $PORT ==="
  bash "$SCRIPT_DIR/portcheck.sh" "$PORT"
  echo
  echo "=== recent app log (last 100 lines) ==="
  bash "$SCRIPT_DIR/appctl.sh" logs
} 2>&1 | tee "$OUT"

echo
ok "Bundle saved to: $OUT"
