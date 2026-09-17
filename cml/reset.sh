#!/usr/bin/env bash
# Wipe local demo state (SQLite DB, Chroma index, uploaded storage) so the next
# `setup.sh` starts clean. Only touches SQLite-backed local files — never
# touches Impala/CDP data.
# Usage: bash cml/reset.sh [--yes]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

YES=0
for arg in "$@"; do [[ "$arg" == "--yes" ]] && YES=1; done

db_backend="$(env_get DB_BACKEND)"; db_backend="${db_backend:-sqlite}"
if [[ "$db_backend" == "impala" ]]; then
  warn "DB_BACKEND=impala — this script will NOT touch remote CDP data."
fi

TARGETS=(
  "$BACKEND/insurance.db"
  "$BACKEND/chroma_db"
  "$BACKEND/storage"
)

echo "This will permanently delete local demo state:"
for t in "${TARGETS[@]}"; do echo "  - $t"; done

if [[ "$YES" -ne 1 ]]; then
  read -r -p "Type 'reset' to confirm: " CONFIRM
  [[ "$CONFIRM" == "reset" ]] || { warn "Aborted — nothing deleted."; exit 1; }
fi

for t in "${TARGETS[@]}"; do
  if [[ -e "$t" ]]; then rm -rf "$t"; ok "removed $t"; else warn "$t did not exist"; fi
done

echo
echo "Next: bash cml/cli.sh setup --reset-db"
