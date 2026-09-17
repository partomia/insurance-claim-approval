#!/usr/bin/env bash
# Register the insurance lakehouse Airflow DAG on CDE — sourced directly from
# the CDE Git repository (same one deploy_jobs.sh creates/syncs), not a
# manually-uploaded `files` Resource.
#
# Requires: CDE CLI configured, an Airflow-enabled CDE virtual cluster, and
# the four jobs from deploy_jobs.sh already created (deploy_jobs.sh also
# creates the repository resource — run that first if you haven't).
#
# Usage:
#   ./cde/scripts/deploy_dag.sh

set -euo pipefail

REPO_NAME="insurance-claim-approval-repo"
DAG_JOB_NAME="insurance-lakehouse-pipeline-dag"
DAG_PATH_IN_REPO="cde/dags/insurance_lakehouse_dag.py"

echo "==> Syncing repository to latest commit: ${REPO_NAME}"
cde repository sync --name "${REPO_NAME}"

echo "==> Creating/updating Airflow job for DAG: ${DAG_JOB_NAME}"
if cde job describe --name "${DAG_JOB_NAME}" &>/dev/null; then
  cde job update --name "${DAG_JOB_NAME}" \
    --dag-file "${DAG_PATH_IN_REPO}" \
    --mount-1-resource "${REPO_NAME}"
else
  cde job create --name "${DAG_JOB_NAME}" \
    --type airflow \
    --dag-file "${DAG_PATH_IN_REPO}" \
    --mount-1-resource "${REPO_NAME}"
fi

echo "DAG deployed from repository. Find it in CDE Airflow UI -> DAGs -> insurance_lakehouse_pipeline."
echo ""
echo "After your next 'git push', re-sync + re-run this script to pick up DAG changes:"
echo "  cde repository sync --name ${REPO_NAME} && ./cde/scripts/deploy_dag.sh"
