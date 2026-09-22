#!/usr/bin/env bash
# Phase 1 of the Cloudera datalakehouse story: create + seed a small Iceberg
# schema (insurance_lakehouse.policy_master / policy_clauses) via Impala.
#
# Independent of DB_BACKEND — the app keeps running on SQLite. This only
# proves out Iceberg read/write on the same CDP cluster, reusing the
# IMPALA_* connection settings already in backend/.env.
#
#   bash cml/cli.sh lakehouse seed     # create schema/tables + insert demo rows
#   bash cml/cli.sh lakehouse verify   # read-only: counts + sample rows + DDL check
#
# Phase 3 (see cde/README.md): pull the CDE-pipeline-produced gold tables
# (policy_master, policy_clauses, policy_risk_signals) into the app's live
# SQLite DB + Chroma RAG index.
#
#   bash cml/cli.sh lakehouse ingest          # ingest + index into Chroma
#   bash cml/cli.sh lakehouse ingest --no-rag # DB only, skip Chroma indexing
#
# Closing the loop (see cde/README.md § Closing the loop): push app-filed,
# decided claims into the lakehouse's app_claims_raw bronze table, so the
# CDE claims-analytics pipeline's fraud/risk analytics include real claims
# too, not just synthetic history.
#
#   bash cml/cli.sh lakehouse export-claims           # export + mark exported
#   bash cml/cli.sh lakehouse export-claims --dry-run # preview only
#
# Iceberg time travel / audit (see cde/README.md § Iceberg time travel):
# the gold tables write via MERGE INTO now, so every pipeline run commits
# a real snapshot -- these list/query that snapshot history via Impala.
#
#   bash cml/cli.sh lakehouse history --table policy_risk_signals
#   bash cml/cli.sh lakehouse as-of --table policy_risk_signals \
#       --policy-number LH-POL-2059 --snapshot <id-from-history>
#
set -euo pipefail
# shellcheck source=cml/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

mode="${1:-seed}"
shift || true
case "$mode" in
  seed|verify|ingest|export-claims|history|as-of) ;;
  *) err "Usage: cml/cli.sh lakehouse <seed|verify|ingest|export-claims|history|as-of> [flags]"; exit 2 ;;
esac

[[ -f "$BACKEND/.env" ]] || { err "backend/.env missing — run 'bash cml/cli.sh setup' first"; exit 1; }

auth="$(env_get IMPALA_AUTH_MECHANISM)"; auth="${auth:-GSSAPI}"
host="$(env_get IMPALA_HOST)"
if [[ -z "$host" ]]; then
  err "IMPALA_HOST is empty in backend/.env — set the IMPALA_* block (see backend/.env.example)"
  exit 1
fi
if [[ "$auth" == "GSSAPI" ]]; then
  if command -v klist >/dev/null 2>&1 && ! klist -s 2>/dev/null; then
    warn "No active Kerberos ticket detected — run 'kinit' first if this fails."
  fi
fi

ensure_uv
fix_openssl_ciphers_if_broken

lakehouse_db="$(env_get LAKEHOUSE_DATABASE)"; lakehouse_db="${lakehouse_db:-insurance_lakehouse}"
log "Running lakehouse $mode against $host (schema: $lakehouse_db)"
cd "$BACKEND"
if [[ "$mode" == "ingest" ]]; then
  uv run python scripts/ingest_lakehouse.py "$@"
elif [[ "$mode" == "export-claims" ]]; then
  uv run python scripts/export_claims_to_lakehouse.py "$@"
elif [[ "$mode" == "history" || "$mode" == "as-of" ]]; then
  uv run python scripts/lakehouse_time_travel.py "$mode" "$@"
else
  uv run python scripts/lakehouse_seed.py "$mode"
fi
