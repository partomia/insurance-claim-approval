#!/usr/bin/env bash
# Upload the insurance lakehouse Airflow DAG to CDE's Airflow service.
# Same pattern as Cloudera-CDE-Workshop-with-Orchestration-and-CI-CD/scripts/deploy_dag.sh.
#
# Requires: CDE CLI configured, an Airflow-enabled CDE virtual cluster, and
# the four jobs from deploy_jobs.sh already created.
#
# Usage:
#   ./cde/scripts/deploy_dag.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DAG_RESOURCE="insurance-lakehouse-dags"
DAG_FILE="${REPO_ROOT}/cde/dags/insurance_lakehouse_dag.py"

echo "==> Creating/updating DAG resource: ${DAG_RESOURCE}"
cde resource create --name "${DAG_RESOURCE}" --type files 2>/dev/null || true

echo "==> Uploading DAG: ${DAG_FILE}"
cde resource upload --name "${DAG_RESOURCE}" --local-path "${DAG_FILE}"

echo "==> Creating/updating Airflow job for DAG"
if cde job describe --name "insurance-lakehouse-pipeline-dag" &>/dev/null; then
  cde job update --name "insurance-lakehouse-pipeline-dag" \
    --dag-file "insurance_lakehouse_dag.py" \
    --mount-1-resource "${DAG_RESOURCE}"
else
  cde job create --name "insurance-lakehouse-pipeline-dag" \
    --type airflow \
    --dag-file "insurance_lakehouse_dag.py" \
    --mount-1-resource "${DAG_RESOURCE}"
fi

echo "DAG deployed. Find it in CDE Airflow UI -> DAGs -> insurance_lakehouse_pipeline."
