#!/usr/bin/env bash
# Item 3, step 3: a repeatable drill that manufactures a genuine, meaningful
# day-over-day diff for the Iceberg time-travel demo ON DEMAND -- instead of
# relying on a real calendar day boundary to cross (which step 1's
# verification happened to catch as a one-off, see cde/README.md § Iceberg
# time travel).
#
# How: generate_bronze.py / generate_claims_bronze.py accept an optional 2nd
# arg -- a raw seed int, or a YYYY-MM-DD date string (converted to the same
# seed formula generate_policy_rows/generate_claim_rows default to). Passing
# an *earlier* date reproduces exactly what those jobs would have generated
# if they'd actually run on that day, without touching the real anchor dates
# (effective_date/expiry_date/incident_date/filed_date still anchor to *now*,
# so nothing looks artificially expired -- only the attribute *values*
# simulate the earlier day). Run once with an earlier date, then once with
# no override (defaults to today), and you get two meaningfully different
# gold snapshots to time-travel between -- every time, on demand.
#
# Usage:
#   ./cde/scripts/time_travel_drill.sh [earlier-date]
#   # earlier-date defaults to 7 days before today, format YYYY-MM-DD
#
# Requires: CDE CLI configured (~/.cde/config.yaml), jobs already deployed
# (./cde/scripts/deploy_jobs.sh), python-env resource status "ready".
set -euo pipefail

EARLIER="${1:-$(python3 -c "import datetime; print((datetime.date.today() - datetime.timedelta(days=7)).isoformat())")}"

echo "This drill runs the full generate -> validate -> transform -> curate"
echo "chain TWICE:"
echo "  1) seeded as if it were ${EARLIER} (an 'earlier' snapshot)"
echo "  2) seeded normally as today (the 'current' snapshot)"
echo ""
echo "Each run commits a new Iceberg snapshot via MERGE INTO (Item 3 step 1)"
echo "-- nothing is dropped or lost between them."
echo ""

run_chain() {
  local n_policies=$1 seed_arg=$2 n_claims=$3

  echo "==> generate-bronze (seed: ${seed_arg:-today})"
  cde job run --name rsingh-insurance-generate-bronze --arg "$n_policies" --arg "$seed_arg" --wait
  echo "==> validate-bronze"
  cde job run --name rsingh-insurance-validate-bronze --wait
  echo "==> transform-silver"
  cde job run --name rsingh-insurance-transform-silver --wait
  echo "==> curate-gold"
  cde job run --name rsingh-insurance-curate-gold --wait

  echo "==> generate-claims-bronze (seed: ${seed_arg:-today})"
  cde job run --name rsingh-insurance-generate-claims-bronze --arg "$n_claims" --arg "$seed_arg" --wait
  echo "==> validate-claims-bronze"
  cde job run --name rsingh-insurance-validate-claims-bronze --wait
  echo "==> transform-claims-silver"
  cde job run --name rsingh-insurance-transform-claims-silver --wait
  echo "==> curate-risk-signals-gold"
  cde job run --name rsingh-insurance-curate-risk-signals-gold --wait
}

echo "=================================================================="
echo " Pass 1/2 -- simulating ${EARLIER}"
echo "=================================================================="
run_chain 60 "$EARLIER" 4000

echo ""
echo "=================================================================="
echo " Pass 2/2 -- today (no seed override)"
echo "=================================================================="
run_chain 60 "" 4000

echo ""
echo "Done. Two meaningfully different gold snapshots now exist. Try (from"
echo "a CAI session, after 'git pull'):"
echo "  bash cml/cli.sh lakehouse history --table policy_risk_signals"
echo "  bash cml/cli.sh lakehouse as-of --table policy_risk_signals \\"
echo "    --policy-number LH-POL-2000 --snapshot <id-from-history-above>"
