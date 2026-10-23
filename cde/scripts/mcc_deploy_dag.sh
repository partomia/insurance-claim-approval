#!/usr/bin/env bash
# Register/update the Airflow DAGs as `--type airflow` CDE jobs whose DAG files come from the files
# resource rsingh-mcc-code (run mcc_deploy_code.sh first). Copied from O-G-Asset-Integrity-Lakehouse.
#   rsingh-mcc-orchestration  cde/dags/mcc_dag.py       DAG mcc_motor_claims (nightly batch)
#   rsingh-mcc-live-stream    cde/dags/mcc_live_dag.py  DAG mcc_live_stream (the day's live stream)
# Both are created paused; unpause them to let their schedules run (the Airflow API refuses it):
#
#   ./cde/scripts/mcc_deploy_dag.sh
#   cde job schedule unpause --name rsingh-mcc-orchestration
#   cde job schedule unpause --name rsingh-mcc-live-stream
#   manual batch run: Airflow UI -> mcc_motor_claims -> Trigger DAG w/ config {"business_date": "2026-10-17"}
#
# Extending end_date of an unpaused DAG makes Airflow run the latest missed interval at once
# (catchup=False still runs the most recent one): do not start a manual catch-up for that date too.

set -euo pipefail

RESOURCE="${RESOURCE:-rsingh-mcc-code}"
DAGS=("rsingh-mcc-orchestration:cde/dags/mcc_dag.py" "rsingh-mcc-live-stream:cde/dags/mcc_live_dag.py")

for entry in "${DAGS[@]}"; do
  name="${entry%%:*}" path="${entry#*:}"
  if cde job describe --name "${name}" &>/dev/null; then
    echo "==> Updating ${name} (${path})"
    cde job update --name "${name}" --dag-file "${path}" --mount-1-resource "${RESOURCE}" >/dev/null
  else
    echo "==> Creating ${name} (${path}), paused"
    cde job create --name "${name}" --type airflow --dag-file "${path}" --mount-1-resource "${RESOURCE}" >/dev/null
  fi
done
echo "Give Airflow ~30s to re-parse before triggering."
