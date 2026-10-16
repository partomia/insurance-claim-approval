"""
Airflow DAG (CDE): one batch of the Motor Claim Copilot lakehouse, one business date per run.
Copied from O-G-Asset-Integrity-Lakehouse cde/dags/ogx_dag.py and adapted.

  land_sources -> ingest_bronze -> build_silver -> build_mdm -> build_gold -> reconcile
    -> batch_complete

land_sources stands in for the insurer's source systems (garage network, policy admin, credit
bureau, claims, telematics) dropping their files on the landing zone. The Kafka stream (crash
events, claim events) does not go through this DAG for manual runs: the long-running job
rsingh-mcc-stream-bronze keeps bronze current. reconcile runs whatever happened upstream (trigger
rule all_done), so a failed batch still gets its report in ref.recon_results; batch_complete
needs every stage to have succeeded, so the run itself is red for a failed batch.

The semantic layer runs on CDW Impala after the batch:
  python scripts/run_semantic.py --engine impala --dates <date>

Scheduled nightly at 02:00 IST (20:30 UTC) for the business dates in lakehouse.json
"scheduled_dates" (2026-10-19 .. 2026-10-21): each run closes the UTC day its data interval ends
on and replays that day's stream first (producer backfill, then the bronze stream with an
available-now trigger; stop the long-running stream before unpausing). Created paused.
Manual runs use params.business_date (Trigger DAG w/ config), in date order, and skip the stream:
  {"business_date": "2026-10-17"}
Job names must match cde/scripts/mcc_deploy_jobs.sh (CDEJobRunOperator fails with 404 otherwise).
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import ShortCircuitOperator
from cloudera.cdp.airflow.operators.cde_operator import CDEJobRunOperator

JOB_PREFIX = "rsingh-mcc"
DB_PREFIX = "rsingh_mcc"
LANDING = "s3a://federal-buk-574bcea0/data/IB/rsingh_mcc/landing"
CHECKPOINTS = "s3a://federal-buk-574bcea0/data/IB/rsingh_mcc/checkpoints"
SCHEDULED = "dag_run.run_type == 'scheduled'"
BUSINESS_DATE = ("{{ data_interval_end.strftime('%Y-%m-%d') if " + SCHEDULED +
                 " else params.business_date }}")

default_args = {
    "owner": "claims-data",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
    # the virtual cluster is shared: a stage stuck in "starting" must not hold quota for days
    "execution_timeout": timedelta(minutes=60),
}

with DAG(
    dag_id="mcc_motor_claims",
    description="Insurer sources -> bronze / silver / MDM / gold on Iceberg, with reconciliation",
    default_args=default_args,
    schedule_interval="30 20 * * *",
    # first interval ends 2026-10-19 20:30 UTC (business date 10-19), the last starts on end_date
    start_date=datetime(2026, 10, 18, 20, 30),
    end_date=datetime(2026, 10, 20, 20, 30),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=4),
    params={"business_date": "2026-10-17", "bronze_mode": "normal"},
    tags=["lakehouse", "iceberg", "mdm", "reconciliation", "insurance"],
) as dag:

    def stage(task_id: str, job: str, *extra: str, **kwargs) -> CDEJobRunOperator:
        # run-time args replace the job's own, so every task passes the full set
        return CDEJobRunOperator(
            task_id=task_id,
            job_name=f"{JOB_PREFIX}-{job}",
            overrides={"spark": {"args": ["--business-date", BUSINESS_DATE, "--landing", LANDING,
                                          "--db-prefix", DB_PREFIX, "--pipeline-run", "{{ run_id }}", *extra]}},
            wait=True,
            **kwargs,
        )

    land = stage("land_sources", "land")
    bronze = stage("ingest_bronze", "bronze", "--mode", "{{ params.bronze_mode }}")
    silver = stage("build_silver", "silver")
    mdm = stage("build_mdm", "mdm")
    gold = stage("build_gold", "gold")
    recon = stage("reconcile", "recon", trigger_rule="all_done", retries=0)
    batch_complete = EmptyOperator(task_id="batch_complete", trigger_rule="all_success")

    # the day's stream: scheduled runs only (a manual run of an old date would replay it)
    is_scheduled = ShortCircuitOperator(
        task_id="is_scheduled", python_callable=lambda dag_run, **_: dag_run.run_type == "scheduled",
        ignore_downstream_trigger_rules=False)

    def stream_job(task_id: str, job: str, *args: str) -> CDEJobRunOperator:
        return CDEJobRunOperator(task_id=task_id, job_name=f"{JOB_PREFIX}-{job}",
                                 overrides={"spark": {"args": list(args)}}, wait=True)

    produce = stream_job("stream_produce", "stream-produce", "--mode", "backfill",
                         "--start-date", BUSINESS_DATE, "--days", "1")
    stream_bronze = stream_job("stream_bronze", "stream-bronze", "--db-prefix", DB_PREFIX,
                               "--checkpoints", CHECKPOINTS, "--trigger", "available-now",
                               "--starting-offsets", "earliest")
    stream_done = EmptyOperator(task_id="stream_done", trigger_rule="none_failed")

    land >> bronze >> silver >> mdm >> gold >> recon
    # manual run: produce and stream_bronze are skipped, stream_done (none_failed) still lets silver run
    is_scheduled >> produce >> stream_bronze >> stream_done >> silver
    [gold, recon] >> batch_complete
