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
set -euo pipefail
# shellcheck source=cml/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

mode="${1:-seed}"
shift || true
case "$mode" in
  seed|verify|ingest) ;;
  *) err "Usage: cml/cli.sh lakehouse <seed|verify|ingest> [--no-rag]"; exit 2 ;;
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
else
  uv run python scripts/lakehouse_seed.py "$mode"
fi
