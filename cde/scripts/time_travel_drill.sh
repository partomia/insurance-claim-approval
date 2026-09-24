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
#
# IMPORTANT gotcha: Pass 2 always reseeds as *today* -- if this drill (or
# the normal scheduled pipeline) has already run once today before you run
# this script, Pass 2 reproduces byte-identical data to that earlier
# same-day run (same seed = same RNG draws), so a MERGE INTO between them
# is a no-op except for `ingested_at`. The diff you actually want is
# Pass 1's snapshot (seeded as $EARLIER, guaranteed different) vs. CURRENT
# or vs. Pass 2 -- NOT two same-day "today" snapshots against each other.
# This script prints wall-clock timestamps around each pass so you can
# match them against `creation_time` in `lakehouse history`'s output and
# pick the right snapshot_id.
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

  echo "==> generate-customer-profile-bronze (seed: ${seed_arg:-today})"
  cde job run --name rsingh-insurance-generate-customer-profile-bronze --arg 800 --arg "$seed_arg" --wait
  echo "==> transform-customer-profile-silver"
  cde job run --name rsingh-insurance-transform-customer-profile-silver --wait
  echo "==> curate-customer-profile-gold"
  cde job run --name rsingh-insurance-curate-customer-profile-gold --wait
}

echo "Wall-clock BEFORE pass 1: $(date -u '+%Y-%m-%d %H:%M:%S') UTC"
echo "=================================================================="
echo " Pass 1/2 -- simulating ${EARLIER}"
echo "=================================================================="
run_chain 60 "$EARLIER" 4000
PASS1_DONE="$(date -u '+%Y-%m-%d %H:%M:%S')"
echo "Wall-clock AFTER pass 1 / BEFORE pass 2: ${PASS1_DONE} UTC  <-- the"
echo "gold-table snapshot committed just before this line is the one you"
echo "want for the demo diff (seeded as ${EARLIER}, guaranteed different)."

echo ""
echo "=================================================================="
echo " Pass 2/2 -- today (no seed override)"
echo "=================================================================="
run_chain 60 "" 4000
echo "Wall-clock AFTER pass 2: $(date -u '+%Y-%m-%d %H:%M:%S') UTC"

echo ""
echo "=================================================================="
echo "Done."
echo ""
echo "IMPORTANT: pick the RIGHT snapshot pair for the demo diff. Run:"
echo "  bash cml/cli.sh lakehouse history --table policy_risk_signals"
echo "and find the row whose creation_time is closest to (just before)"
echo "${PASS1_DONE} UTC above -- that snapshot was seeded as ${EARLIER} and"
echo "is guaranteed to differ from CURRENT. Then:"
echo "  bash cml/cli.sh lakehouse as-of --table policy_risk_signals \\"
echo "    --policy-number <LH-POL-XXXX> --snapshot <that-snapshot-id>"
echo ""
echo "Do NOT diff two 'today'-seeded snapshots against each other (e.g. the"
echo "one right after pass 1's timestamp vs. the very last one from pass 2)"
echo "-- if the pipeline already ran once today before this drill, pass 2's"
echo "snapshot reproduces byte-identical data (same seed), so the only"
echo "column that differs is ingested_at."
