#!/usr/bin/env bash
# Thin wrapper around backend/scripts/lakehouse_risk_claim_test.py — a
# reusable, committed test harness for the lakehouse risk -> decision
# pipeline (see cde/README.md "Feed fraud_risk_score/claim_risk_band into
# the live decision engine"), instead of hand-typing multi-step curl chains.
#
#   bash cml/cli.sh test-claim find --band HIGH --not-expired
#   bash cml/cli.sh test-claim submit --policy-number LH-POL-2059
#
# `find` is DB-direct (works even if the app isn't running). `submit` needs
# the app already running (`cml/cli.sh start`/`restart`) — resolves whichever
# port it actually bound, same as smoke.sh, unless --base-url overrides it.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

mode="${1:-}"
shift || true
case "$mode" in
  find|submit) ;;
  *) err "Usage: cml/cli.sh test-claim <find|submit> [flags] — see backend/scripts/lakehouse_risk_claim_test.py --help"; exit 2 ;;
esac

ensure_uv
fix_openssl_ciphers_if_broken

extra_args=("$@")
if [[ "$mode" == "submit" ]]; then
  # Inject a default --base-url (from the same port-resolution logic as
  # smoke.sh) only if the caller didn't already pass one.
  if [[ ! " ${extra_args[*]:-} " =~ " --base-url " ]]; then
    extra_args+=(--base-url "http://127.0.0.1:$(resolve_app_port)")
  fi
fi

start_logging "test-claim-$mode"
cd "$BACKEND"
uv run python scripts/lakehouse_risk_claim_test.py "$mode" "${extra_args[@]}"
