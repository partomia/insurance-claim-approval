#!/usr/bin/env bash
# Deploy / update the insurance lakehouse medallion Spark jobs on CDE —
# sourced from a CDE Repository (Git integration) instead of manually
# uploading each script as a `files` Resource.
#
# Jobs reference their application file directly from the synced repo path
# (e.g. cde/jobs/generate/generate_bronze.py) via --mount-1-resource pointing
# at the Repository. After every `git push`, re-run this script (or just
# `cde repository sync --name "${REPO_NAME}"`) to pick up the new commit —
# no re-upload step.
#
# Naming: uses the `rsingh-insurance-*` prefix already established for this
# repo/vcluster (see rsingh-insurance-claim-cai-pipeline) to avoid collisions
# on a shared vcluster. Rename via the vars below if you're a different user.
#
# Requires: CDE CLI installed + configured (~/.cde/config.yaml with
# vcluster-endpoint).
#
# Usage:
#   # Public repo:
#   ./cde/scripts/deploy_jobs.sh
#
#   # Private repo, only used if the repository doesn't already exist.
#   # NOTE: --credential takes the NAME of a stored CDE credential object,
#   # not the raw token -- store it first (interactive password prompt,
#   # paste your GitHub PAT there):
#   #   cde credential create --name my-github-pat --type basic --username <github-user>
#   GIT_CREDENTIAL=my-github-pat ./cde/scripts/deploy_jobs.sh

set -euo pipefail

REPO_URL="https://github.com/partomia/insurance-claim-approval"
REPO_BRANCH="main"
REPO_NAME="rsingh-insurance-claim-cai-pipeline"
PYTHON_ENV="rsingh-insurance-lakehouse-python-env"
REQUIREMENTS_LOCAL_PATH="$(cd "$(dirname "$0")/../.." && pwd)/cde/resources/requirements.txt"

echo "==> Repository: ${REPO_NAME}"
if cde repository describe --name "${REPO_NAME}" &>/dev/null; then
  echo "    Already exists — syncing to latest commit on ${REPO_BRANCH}"
else
  echo "    Not found — creating"
  create_args=(--name "${REPO_NAME}" --url "${REPO_URL}" --branch "${REPO_BRANCH}")
  if [[ -n "${GIT_CREDENTIAL:-}" ]]; then
    create_args+=(--credential "${GIT_CREDENTIAL}")
  fi
  cde repository create "${create_args[@]}"
fi
cde repository sync --name "${REPO_NAME}"

echo "==> Creating/updating Python environment resource: ${PYTHON_ENV}"
# Empty today (jobs only use PySpark) — separate from the Repository above;
# Repositories can't build a python-env, so this stays a `files`/python-env
# Resource. Adding a real dependency later is editing requirements.txt +
# re-running this script.
cde resource create --name "${PYTHON_ENV}" --type python-env 2>/dev/null || true
cde resource upload --name "${PYTHON_ENV}" \
  --local-path "${REQUIREMENTS_LOCAL_PATH}"

create_or_update_job() {
  local JOB_NAME=$1
  local SCRIPT_PATH_IN_REPO=$2

  # Always delete and recreate to guarantee a clean job definition (no stale args).
  if cde job describe --name "${JOB_NAME}" &>/dev/null; then
    echo "==> Deleting existing job: ${JOB_NAME}"
    cde job delete --name "${JOB_NAME}"
  fi

  echo "==> Creating job: ${JOB_NAME} (${SCRIPT_PATH_IN_REPO})"
  cde job create --name "${JOB_NAME}" \
    --type spark \
    --mount-1-resource "${REPO_NAME}" \
    --application-file "${SCRIPT_PATH_IN_REPO}" \
    --python-env-resource-name "${PYTHON_ENV}"
}

create_or_update_job "rsingh-insurance-generate-bronze"  "cde/jobs/generate/generate_bronze.py"
create_or_update_job "rsingh-insurance-validate-bronze"  "cde/jobs/validate/validate_bronze.py"
create_or_update_job "rsingh-insurance-transform-silver" "cde/jobs/transform/transform_silver.py"
create_or_update_job "rsingh-insurance-curate-gold"      "cde/jobs/curate/curate_gold.py"

# Claims history + risk-signals analytics (runs after curate-gold in the DAG).
create_or_update_job "rsingh-insurance-generate-claims-bronze"   "cde/jobs/generate/generate_claims_bronze.py"
create_or_update_job "rsingh-insurance-validate-claims-bronze"   "cde/jobs/validate/validate_claims_bronze.py"
create_or_update_job "rsingh-insurance-transform-claims-silver"  "cde/jobs/transform/transform_claims_silver.py"
create_or_update_job "rsingh-insurance-curate-risk-signals-gold" "cde/jobs/curate/curate_risk_signals_gold.py"

# Customer profile / bureau signals (independent branch in the DAG) — feeds
# the app's Customer Trust Score.
create_or_update_job "rsingh-insurance-generate-customer-profile-bronze" "cde/jobs/generate/generate_customer_profile_bronze.py"
create_or_update_job "rsingh-insurance-transform-customer-profile-silver" "cde/jobs/transform/transform_customer_profile_silver.py"
create_or_update_job "rsingh-insurance-curate-customer-profile-gold"     "cde/jobs/curate/curate_customer_profile_gold.py"

echo ""
echo "All CDE jobs deployed from repository '${REPO_NAME}' (${REPO_BRANCH})."
echo "Try one directly:"
echo "  cde job run --name rsingh-insurance-generate-bronze --wait"
echo ""
echo "After your next 'git push', just re-sync (no need to re-run this whole script):"
echo "  cde repository sync --name ${REPO_NAME}"
