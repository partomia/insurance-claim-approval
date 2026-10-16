#!/usr/bin/env bash
# The long-running CDE Spark Structured Streaming job and the producer job:
#   rsingh-mcc-stream-bronze   Kafka mcc.* -> bronze.stream_telematics / stream_claim_event / stream_control
#   rsingh-mcc-stream-produce  the claim and telematics producer (create only; run it with
#     cde job run --name rsingh-mcc-stream-produce --arg=--setup --arg=--mode --arg=backfill)
# Copied from O-G-Asset-Integrity-Lakehouse and adapted.
#
#   set -a; source .env; set +a
#   ./cde/scripts/mcc_deploy_streaming.sh create     # create or update both jobs (no run)
#   ./cde/scripts/mcc_deploy_streaming.sh start      # start the bronze stream (resumes from its checkpoint)
#   ./cde/scripts/mcc_deploy_streaming.sh stop       # kill its running runs (checkpoint kept)
#   ./cde/scripts/mcc_deploy_streaming.sh restart    # stop, then start: no gap, no duplicate
#   ./cde/scripts/mcc_deploy_streaming.sh status
#
# Kafka: SASL_SSL / PLAIN with the workload user (MCC_KAFKA_* from .env). The password is passed
# as Spark conf spark.mcc.kafka.password, which Spark redacts in the UI and logs; it is never
# echoed here. The CA: the image's JVM truststore, or the PEM in files resource
# rsingh-mcc-truststore (TRUSTSTORE=1). Streaming jobs have no timeout. Nothing is deleted.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

ACTION="${1:-status}"
RESOURCE="${RESOURCE:-rsingh-mcc-code}"
JOB_PREFIX="${JOB_PREFIX:-rsingh-mcc}"
DB_PREFIX="${DB_PREFIX:-rsingh_mcc}"
CHECKPOINTS="${CHECKPOINTS:-s3a://federal-buk-574bcea0/data/IB/rsingh_mcc/checkpoints}"
KAFKA_PACKAGE="${KAFKA_PACKAGE:-org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.4}"
TRUSTSTORE_RESOURCE="${TRUSTSTORE_RESOURCE:-rsingh-mcc-truststore}"
STARTING_OFFSETS="${STARTING_OFFSETS:-earliest}"
JOBS=("${JOB_PREFIX}-stream-bronze")

RESOURCES=(--driver-cores "${DRIVER_CORES:-2}" --driver-memory "${DRIVER_MEMORY:-4g}"
           --executor-cores "${EXECUTOR_CORES:-4}" --executor-memory "${EXECUTOR_MEMORY:-8g}"
           --min-executors 1 --initial-executors 1 --max-executors "${MAX_EXECUTORS:-2}"
           --conf spark.sql.shuffle.partitions=8)

kafka_conf() {
  : "${MCC_KAFKA_BOOTSTRAP:?source .env first}" "${MCC_KAFKA_USER:?}" "${MCC_KAFKA_PASSWORD:?}"
  KCONF=(--conf "spark.jars.packages=${KAFKA_PACKAGE}"
         --conf "spark.mcc.kafka.bootstrap=${MCC_KAFKA_BOOTSTRAP}"
         --conf "spark.mcc.kafka.protocol=${MCC_KAFKA_SECURITY_PROTOCOL:-SASL_SSL}"
         --conf "spark.mcc.kafka.mechanism=${MCC_KAFKA_SASL_MECHANISM:-PLAIN}"
         --conf "spark.mcc.kafka.user=${MCC_KAFKA_USER}"
         --conf "spark.mcc.kafka.password=${MCC_KAFKA_PASSWORD}")
  if [[ "${TRUSTSTORE:-0}" == "1" ]]; then
    KCONF+=(--mount-2-resource "${TRUSTSTORE_RESOURCE}" --mount-2-prefix truststore
            --conf "spark.mcc.kafka.truststore=/app/mount/truststore/ca.pem")
  fi
}

upsert() {
  local name=$1 file=$2; shift 2
  if cde job describe --name "${name}" &>/dev/null; then
    echo "==> Updating ${name}"
    cde job update --name "${name}" --application-file "${file}" "${RESOURCES[@]}" "$@" >/dev/null
  else
    echo "==> Creating ${name} (${file})"
    cde job create --name "${name}" --type spark --mount-1-resource "${RESOURCE}" \
      --application-file "${file}" "${RESOURCES[@]}" "$@" >/dev/null
  fi
}

running_ids() {
  cde run list --filter "job[eq]$1" --filter "status[rlike]^(starting|running)$" 2>/dev/null \
    | python3 -c "import json,sys; print(' '.join(str(r['id']) for r in json.load(sys.stdin)))"
}

case "${ACTION}" in
  create)
    if [[ "${TRUSTSTORE:-0}" == "1" ]]; then
      cde resource describe --name "${TRUSTSTORE_RESOURCE}" &>/dev/null || \
        cde resource create --name "${TRUSTSTORE_RESOURCE}" --type files
      cde resource upload --name "${TRUSTSTORE_RESOURCE}" --local-path "${MCC_KAFKA_CA_PEM/#\~/$HOME}" \
        --resource-path ca.pem >/dev/null
    fi
    kafka_conf
    upsert "${JOBS[0]}" cde/jobs/stream_bronze.py "${KCONF[@]}" \
      --arg=--db-prefix --arg="${DB_PREFIX}" --arg=--checkpoints --arg="${CHECKPOINTS}" \
      --arg=--starting-offsets --arg="${STARTING_OFFSETS}"
    upsert "${JOB_PREFIX}-stream-produce" cde/jobs/stream_produce.py "${KCONF[@]}" --arg=--setup
    ;;
  start)
    for j in "${JOBS[@]}"; do
      if [[ -n "$(running_ids "$j")" ]]; then echo "$j: already running"; else
        echo "$j: run $(cde job run --name "$j" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"; fi
    done
    ;;
  stop)
    for j in "${JOBS[@]}"; do
      for id in $(running_ids "$j"); do echo "$j: killing run ${id}"; cde run kill --id "${id}"; done
    done
    ;;
  restart)
    "$0" stop; sleep 20; "$0" start
    ;;
  status)
    for j in "${JOBS[@]}" "${JOB_PREFIX}-stream-produce"; do
      cde run list --filter "job[eq]$j" 2>/dev/null | python3 -c "
import json,sys
runs=sorted(json.load(sys.stdin), key=lambda r: r['id'])[-3:]
print('$j:', ', '.join(f\"run {r['id']} {r['status']}\" for r in runs) or 'never run')"
    done
    ;;
  *) echo "usage: $0 create|start|stop|restart|status"; exit 2 ;;
esac
