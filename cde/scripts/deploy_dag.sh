#!/usr/bin/env bash
# Register the insurance lakehouse Airflow DAG on CDE — sourced directly from
# the CDE Git repository (same one deploy_jobs.sh creates/syncs), as a proper
# `--type airflow` job (not a `spark` job pointed at a DAG file, which will
# not actually orchestrate anything — spark-submitting a DAG script just
# fails on `import airflow`, it doesn't register/schedule it).
#
# Requires: CDE CLI configured, an Airflow-enabled CDE virtual cluster, and
# the four jobs from deploy_jobs.sh already created (deploy_jobs.sh also
# creates/syncs the repository resource — run that first if you haven't).
#
# Usage:
#   ./cde/scripts/deploy_dag.sh

set -euo pipefail

REPO_NAME="rsingh-insurance-claim-cai-pipeline"
DAG_JOB_NAME="rsingh-insurance-claim-cai-pipeline-orchestration"
DAG_PATH_IN_REPO="cde/dags/insurance_lakehouse_dag.py"

echo "==> Syncing repository to latest commit: ${REPO_NAME}"
cde repository sync --name "${REPO_NAME}"

if cde job describe --name "${DAG_JOB_NAME}" &>/dev/null; then
  existing_type="$(cde job describe --name "${DAG_JOB_NAME}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('type'))")"
  if [[ "${existing_type}" != "airflow" ]]; then
    echo "==> Existing job '${DAG_JOB_NAME}' has wrong type (${existing_type}) — deleting to recreate as airflow"
    cde job delete --name "${DAG_JOB_NAME}"
    cde job create --name "${DAG_JOB_NAME}" \
      --type airflow \
      --dag-file "${DAG_PATH_IN_REPO}" \
      --mount-1-resource "${REPO_NAME}"
  else
    echo "==> Updating existing airflow job: ${DAG_JOB_NAME}"
    cde job update --name "${DAG_JOB_NAME}" \
      --dag-file "${DAG_PATH_IN_REPO}" \
      --mount-1-resource "${REPO_NAME}"
  fi
else
  echo "==> Creating airflow job: ${DAG_JOB_NAME}"
  cde job create --name "${DAG_JOB_NAME}" \
    --type airflow \
    --dag-file "${DAG_PATH_IN_REPO}" \
    --mount-1-resource "${REPO_NAME}"
fi

echo "DAG deployed from repository. Find it in CDE Airflow UI -> DAGs -> insurance_lakehouse_pipeline."
echo ""
echo "After your next 'git push', re-sync + re-run this script to pick up DAG changes:"
echo "  cde repository sync --name ${REPO_NAME} && ./cde/scripts/deploy_dag.sh"
