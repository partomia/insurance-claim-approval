#!/usr/bin/env bash
# Deploy / update the insurance lakehouse medallion Spark jobs on CDE.
# Same pattern as Cloudera-CDE-Workshop-with-Orchestration-and-CI-CD/scripts/deploy_jobs.sh.
#
# Requires: CDE CLI installed + configured (~/.cde/config.yaml with
# vcluster-endpoint), and a Python env resource matching this vcluster's
# Spark/Iceberg runtime (no extra deps needed — all jobs use only PySpark).
#
# Usage:
#   ./cde/scripts/deploy_jobs.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RESOURCE_NAME="insurance-lakehouse-files"
PYTHON_ENV="insurance-lakehouse-python-env"

echo "==> Creating/updating CDE file resource: ${RESOURCE_NAME}"
cde resource create --name "${RESOURCE_NAME}" --type files 2>/dev/null || true

echo "==> Uploading job scripts"
cde resource upload --name "${RESOURCE_NAME}" \
  --local-path "${REPO_ROOT}/cde/jobs/generate/generate_bronze.py" \
  --local-path "${REPO_ROOT}/cde/jobs/validate/validate_bronze.py" \
  --local-path "${REPO_ROOT}/cde/jobs/transform/transform_silver.py" \
  --local-path "${REPO_ROOT}/cde/jobs/curate/curate_gold.py"

echo "==> Creating/updating Python environment resource: ${PYTHON_ENV}"
# Empty today (jobs only use PySpark) — wired up now so adding a dependency
# later is just editing cde/resources/requirements.txt + re-running this
# script (or syncing via the CDE UI's Repositories feature), no job changes.
cde resource create --name "${PYTHON_ENV}" --type python-env 2>/dev/null || true
cde resource upload --name "${PYTHON_ENV}" \
  --local-path "${REPO_ROOT}/cde/resources/requirements.txt"

create_or_update_job() {
  local JOB_NAME=$1
  local SCRIPT=$2

  # Always delete and recreate to guarantee a clean job definition (no stale args).
  if cde job describe --name "${JOB_NAME}" &>/dev/null; then
    echo "==> Deleting existing job: ${JOB_NAME}"
    cde job delete --name "${JOB_NAME}"
  fi

  echo "==> Creating job: ${JOB_NAME}"
  cde job create --name "${JOB_NAME}" \
    --type spark \
    --application-file "${SCRIPT}" \
    --mount-1-resource "${RESOURCE_NAME}" \
    --python-env-resource-name "${PYTHON_ENV}"
}

create_or_update_job "insurance-generate-bronze"  "generate_bronze.py"
create_or_update_job "insurance-validate-bronze"  "validate_bronze.py"
create_or_update_job "insurance-transform-silver" "transform_silver.py"
create_or_update_job "insurance-curate-gold"      "curate_gold.py"

echo ""
echo "All CDE jobs deployed. Try one directly:"
echo "  cde job run --name insurance-generate-bronze --wait"
