"""
Airflow DAG (CDE): one batch of the Motor Claim Copilot lakehouse, one business date per run.
Copied from O-G-Asset-Integrity-Lakehouse cde/dags/ogx_dag.py and adapted.

  land_sources -> ingest_bronze -> build_silver -> build_mdm -> build_gold -> reconcile
    -> batch_complete -> cai_score_claims          (CAI job mcc-06-score-claims)

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
start_date is in the past so manual runs get tasks (Airflow creates none for a logical date
before start_date); in_window skips every scheduled run whose date is not in SCHEDULED_DATES.
Manual runs use params.business_date (Trigger DAG w/ config), in date order, and skip the stream:
  {"business_date": "2026-10-17"}
Job names must match cde/scripts/mcc_deploy_jobs.sh (CDEJobRunOperator fails with 404 otherwise).

cai_score_claims starts the CAI job with MCC_BUSINESS_DATE in the job run's environment and waits
for it (gold.fact_model_score for that date). Airflow Variables
(cde/scripts/set_airflow_variables.py sets them):
  MCC_CAI_HOST            https://federal-cml.<env>.cloudera.site (CAI workbench URL)
  MCC_CAI_PROJECT_ID      project id of rsingh-motor-claim-copilot
  MCC_CAI_API_KEY         CAI API v2 key
  MCC_CAI_SCORE_JOB_ID    id of mcc-06-score-claims
"""

import time
from datetime import datetime, timedelta

import requests
from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.models import Variable
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from cloudera.cdp.airflow.operators.cde_operator import CDEJobRunOperator

JOB_PREFIX = "rsingh-mcc"
DB_PREFIX = "rsingh_mcc"
LANDING = "s3a://federal-buk-574bcea0/data/IB/rsingh_mcc/landing"
CHECKPOINTS = "s3a://federal-buk-574bcea0/data/IB/rsingh_mcc/checkpoints"
SCHEDULED = "dag_run.run_type == 'scheduled'"
BUSINESS_DATE = ("{{ data_interval_end.strftime('%Y-%m-%d') if " + SCHEDULED +
                 " else params.business_date }}")
CAI_DEADLINE_MIN = 60
SCHEDULED_DATES = ("2026-10-19", "2026-10-20", "2026-10-21")   # lakehouse.json "scheduled_dates"


def in_window(dag_run, data_interval_end, **_) -> bool:
    return dag_run.run_type != "scheduled" or data_interval_end.strftime("%Y-%m-%d") in SCHEDULED_DATES


def trigger_cai_score(business_date: str, run_id: str, **_):
    host = Variable.get("MCC_CAI_HOST", default_var="").rstrip("/")
    if not host:
        raise AirflowException("Airflow Variable MCC_CAI_HOST is not set (cde/scripts/set_airflow_variables.py)")
    project = Variable.get("MCC_CAI_PROJECT_ID")
    job = Variable.get("MCC_CAI_SCORE_JOB_ID")
    headers = {"Authorization": f"Bearer {Variable.get('MCC_CAI_API_KEY')}", "Content-Type": "application/json"}
    env = {"MCC_BUSINESS_DATE": business_date, "MCC_TRIGGERED_BY": f"airflow:{run_id}"}
    url = f"{host}/api/v2/projects/{project}/jobs/{job}/runs"
    resp = requests.post(url, json={"environment": env}, headers=headers, timeout=60)
    resp.raise_for_status()
    cai_run = resp.json()["id"]
    print(f"Started CAI job run {cai_run} (mcc-06-score-claims) with environment: {env}")

    deadline = time.time() + CAI_DEADLINE_MIN * 60
    while time.time() < deadline:
        time.sleep(30)
        r = requests.get(f"{url}/{cai_run}", headers=headers, timeout=60)
        r.raise_for_status()
        status = str(r.json().get("status", "")).lower().replace("engine_", "")
        print(f"CAI run {cai_run}: {status}")
        if status == "succeeded":
            return cai_run
        if status in ("failed", "stopped", "timedout"):
            raise AirflowException(f"CAI job run {cai_run} ended with status {status} (see the job's history in CAI)")
    raise AirflowException(f"CAI job run {cai_run} did not finish within {CAI_DEADLINE_MIN} minutes")

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
    # scheduled business dates 10-16 .. 10-18 are skipped by in_window; the last starts on end_date
    start_date=datetime(2026, 10, 16),
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

    window = ShortCircuitOperator(task_id="in_window", python_callable=in_window)
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

    window >> [land, is_scheduled]
    land >> bronze >> silver >> mdm >> gold >> recon
    # manual run: produce and stream_bronze are skipped, stream_done (none_failed) still lets silver run
    is_scheduled >> produce >> stream_bronze >> stream_done >> silver
    # retries=0: a scoring failure (no champion, endpoint down) is not transient
    score = PythonOperator(task_id="cai_score_claims", python_callable=trigger_cai_score,
                           op_kwargs={"business_date": BUSINESS_DATE, "run_id": "{{ run_id }}"}, retries=0,
                           execution_timeout=timedelta(minutes=CAI_DEADLINE_MIN + 15))
    [gold, recon] >> batch_complete >> score
