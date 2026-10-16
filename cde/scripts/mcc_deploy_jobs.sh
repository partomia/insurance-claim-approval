#!/usr/bin/env bash
# Create (or update in place) one CDE Spark job per pipeline stage, each reading its application
# file from the files resource rsingh-mcc-code (mcc_deploy_code.sh), mounted at /app/mount. The jobs
# need only PySpark and the standard library: no python-env resource. Copied from
# O-G-Asset-Integrity-Lakehouse and adapted (files resource instead of a Git repository).
#
# After a code change: git push, ./cde/scripts/mcc_deploy_code.sh (jobs pick it up on their next run).
#
# Resources (approved): a 2-core / 4 GB driver and 1 to 4 executors of 4 cores / 8 GB.
# Nothing is deleted: an existing job is updated. The go01 jobs (rsingh-insurance-*) are not touched.
#
#   ./cde/scripts/mcc_deploy_code.sh && ./cde/scripts/mcc_deploy_jobs.sh

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

RESOURCE="${RESOURCE:-rsingh-mcc-code}"
JOB_PREFIX="${JOB_PREFIX:-rsingh-mcc}"
DB_PREFIX="${DB_PREFIX:-rsingh_mcc}"
LANDING="${LANDING:-s3a://federal-buk-574bcea0/data/IB/rsingh_mcc/landing}"
RESOURCES=(--driver-cores "${DRIVER_CORES:-2}" --driver-memory "${DRIVER_MEMORY:-4g}"
           --executor-cores "${EXECUTOR_CORES:-4}" --executor-memory "${EXECUTOR_MEMORY:-8g}"
           --min-executors 1 --initial-executors 1 --max-executors "${MAX_EXECUTORS:-4}"
           --conf spark.sql.shuffle.partitions=16
           --conf spark.sql.adaptive.enabled=true)

create_job() {
  local name=$1 file=$2
  if [[ ! -f "${file}" ]]; then echo "==> Skipping ${name}: ${file} not in this checkout"; return; fi
  if cde job describe --name "${name}" &>/dev/null; then
    echo "==> Updating job ${name} (${file})"
    cde job update --name "${name}" --application-file "${file}" "${RESOURCES[@]}" >/dev/null
  else
    echo "==> Creating job ${name} (${file})"
    cde job create --name "${name}" --type spark \
      --mount-1-resource "${RESOURCE}" \
      --application-file "${file}" \
      "${RESOURCES[@]}" \
      --arg=--db-prefix --arg="${DB_PREFIX}" --arg=--landing --arg="${LANDING}" >/dev/null
  fi
}

create_job "${JOB_PREFIX}-land"   "cde/jobs/land_sources.py"
create_job "${JOB_PREFIX}-bronze" "cde/jobs/ingest_bronze.py"
create_job "${JOB_PREFIX}-silver" "cde/jobs/build_silver.py"
create_job "${JOB_PREFIX}-mdm"    "cde/jobs/build_mdm.py"
create_job "${JOB_PREFIX}-gold"   "cde/jobs/build_gold.py"
create_job "${JOB_PREFIX}-recon"  "cde/jobs/reconcile.py"
create_job "${JOB_PREFIX}-stages" "cde/jobs/run_stages.py"

echo ""
echo "Jobs deployed from ${RESOURCE}. One stage by hand (run-time args replace the job's):"
echo "  cde job run --name ${JOB_PREFIX}-bronze --arg=--business-date --arg=2026-10-12 \\"
echo "    --arg=--db-prefix --arg=${DB_PREFIX} --arg=--landing --arg=${LANDING} --wait"
echo "Backfill in one session:"
echo "  cde job run --name ${JOB_PREFIX}-stages --arg=--stages --arg=land,bronze,silver,mdm,gold,recon \\"
echo "    --arg=--dates --arg=2026-10-12,2026-10-13 --arg=--db-prefix --arg=${DB_PREFIX} --arg=--landing --arg=${LANDING}"
echo "Streaming jobs: ./cde/scripts/mcc_deploy_streaming.sh create|start|stop|restart|status"
echo "Then register the DAG: ./cde/scripts/mcc_deploy_dag.sh"
