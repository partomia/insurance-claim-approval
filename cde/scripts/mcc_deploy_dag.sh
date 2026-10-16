#!/usr/bin/env bash
# Register/update the Airflow DAG as a `--type airflow` CDE job whose DAG file comes from the files
# resource rsingh-mcc-code (run mcc_deploy_code.sh first). Copied from O-G-Asset-Integrity-Lakehouse.
# The DAG is created paused; unpause it to let the nightly schedule run:
#
#   ./cde/scripts/mcc_deploy_dag.sh
#   cde job unpause --name rsingh-mcc-orchestration
#   cde job run --name rsingh-mcc-orchestration --config-json '{"business_date": "2026-10-17"}'

set -euo pipefail

RESOURCE="${RESOURCE:-rsingh-mcc-code}"
DAG_JOB_NAME="${DAG_JOB_NAME:-rsingh-mcc-orchestration}"
DAG_PATH="cde/dags/mcc_dag.py"

if cde job describe --name "${DAG_JOB_NAME}" &>/dev/null; then
  echo "==> Updating ${DAG_JOB_NAME}"
  cde job update --name "${DAG_JOB_NAME}" --dag-file "${DAG_PATH}" --mount-1-resource "${RESOURCE}" >/dev/null
  echo "Give Airflow ~30s to re-parse before triggering."
  exit 0
fi

echo "==> Creating ${DAG_JOB_NAME}"
cde job create --name "${DAG_JOB_NAME}" --type airflow --dag-file "${DAG_PATH}" --mount-1-resource "${RESOURCE}" >/dev/null
echo "DAG mcc_motor_claims registered (paused). Trigger one business date:"
echo "  cde job run --name ${DAG_JOB_NAME} --config-json '{\"business_date\": \"2026-10-17\"}'"
