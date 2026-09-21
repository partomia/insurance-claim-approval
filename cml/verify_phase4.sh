#!/usr/bin/env bash
# Phase 4 verification: confirms the insurer-facing risk data (Book of
# Business + the data the Claim Insights risk card reads) is actually
# reachable end-to-end on a running app instance — not just present in
# Impala/Iceberg (`cml/cli.sh lakehouse verify`) or the app DB, but served
# correctly through insurer auth + the /api/insurer/* endpoints.
#
# Requires the app already running (`cml/cli.sh start`/`restart`) — reads
# back whichever port it actually bound, same as smoke.sh.
#
#   bash cml/cli.sh verify-phase4                 # book-of-business + stats only
#   bash cml/cli.sh verify-phase4 --check-claims  # also look for an existing
#                                                  # claim tied to a lakehouse
#                                                  # (LH-POL-*) policy, needed
#                                                  # to see the Claim Insights
#                                                  # risk card on a real claim
#   bash cml/cli.sh verify-phase4 http://host:port [--check-claims]
#
# Demo insurer login (see backend/scripts/seed.py):
#   insurer1@claimcopilot.in / password123 / OTP 112233
#
# Full JSON responses are long, so this mirrors all output to a timestamped
# file under cml/logs/ via start_logging() — same pattern as appctl.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

check_claims=false
base=""
for arg in "$@"; do
  case "$arg" in
    --check-claims) check_claims=true ;;
    http*) base="$arg" ;;
    *) err "Unknown argument: $arg"; exit 2 ;;
  esac
done
[[ -n "$base" ]] || base="http://127.0.0.1:$(resolve_app_port)"

start_logging "verify-phase4"
log "Verifying Phase 4 (insurer risk data) against $base"

INSURER_EMAIL="insurer1@claimcopilot.in"
INSURER_PASSWORD="password123"
INSURER_OTP="112233"

# NOTE: insurer auth lives at the BARE /insurer/auth path, not /api/insurer —
# deliberate (see main.py's _bare_auth_router_prefixes comment). Only the
# data endpoints below are under /api/insurer.
curl -fsS -X POST "$base/insurer/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"$INSURER_EMAIL\",\"password\":\"$INSURER_PASSWORD\"}" >/dev/null \
  || { err "Insurer login failed — is the demo insurer seeded? (backend/scripts/seed.py)"; exit 1; }

TOKEN="$(curl -fsS -X POST "$base/insurer/auth/verify-otp" -H "Content-Type: application/json" \
  -d "{\"email\":\"$INSURER_EMAIL\",\"otp\":\"$INSURER_OTP\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || true)"
[[ -n "$TOKEN" ]] || { err "Could not obtain insurer access token — check the app is running and the demo insurer exists"; exit 1; }
ok "Logged in as $INSURER_EMAIL"

log "GET /api/insurer/book-of-business/stats"
stats="$(curl -fsS "$base/api/insurer/book-of-business/stats" -H "Authorization: Bearer $TOKEN")"
echo "$stats" | python3 -m json.tool

total_policies="$(echo "$stats" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_policies', 0))" 2>/dev/null || echo 0)"
if [[ "$total_policies" -gt 0 ]]; then
  ok "Book of Business stats: $total_policies lakehouse policies with risk signals"
else
  warn "0 policies in Book of Business stats — run 'bash cml/cli.sh lakehouse ingest' first (see cml/README.md § Data lakehouse)"
fi

log "GET /api/insurer/book-of-business (first 2, for shape/spot-check)"
curl -fsS "$base/api/insurer/book-of-business?limit=2" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

if [[ "$check_claims" == true ]]; then
  log "GET /api/insurer/claims?all_statuses=true (looking for a claim tied to an LH-POL-* policy)"
  claims_json="$(curl -fsS "$base/api/insurer/claims?all_statuses=true" -H "Authorization: Bearer $TOKEN")"
  if echo "$claims_json" | grep -q '"LH-POL-'; then
    ok "Found existing claim(s) tied to a lakehouse policy — open one as agent/insurer to check the Claim Insights risk card:"
    echo "$claims_json" | python3 -m json.tool | grep -B2 -A2 '"LH-POL-' || true
  else
    warn "No claims tied to a lakehouse (LH-POL-*) policy yet."
    warn "To test the Claim Insights risk card: reset a lakehouse customer's password with"
    warn "  backend/scripts/set_demo_password.py, log in as them, and submit a claim"
    warn "  against one of their LH-POL-* policies (see cml/README.md § Phase 4)."
  fi
fi

echo
ok "Phase 4 verification complete — full output: see path printed by [log] above"
