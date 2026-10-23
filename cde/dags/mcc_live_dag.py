"""
Airflow DAG (CDE job rsingh-mcc-live-stream): the live Kafka stream of the Motor Claim Copilot
demo, aligned with the nightly batch DAG mcc_motor_claims.

  live_window -> [stream_bronze, stream_produce_live]

On each scheduled date (LIVE_DATES = lakehouse.json "scheduled_dates") at LIVE_START_UTC (09:00
IST) it starts the bronze stream (rsingh-mcc-stream-bronze, 60 s trigger, resumes from its
checkpoint) and the live producer (rsingh-mcc-stream-produce --mode live). Both stop themselves at
LIVE_STOP_UTC (19:00 IST): the stream with --await-seconds, the producer with --duration,
PRODUCER_LEAD_S earlier so its last events are ingested. Nothing runs between 13:30 and 03:30
UTC, and the batch DAG's live_stream_idle sensor waits for this DAG before it replays the day's
stream at 20:30 UTC, so the two never write the stream tables at the same time.

Live events carry their own ids (CE-L..., TM-L...): the nightly backfill of the same date does
not duplicate them. A manual run (Trigger DAG) streams from now until LIVE_STOP_UTC today, and is
skipped after it. The constants must match config/streaming.json live_window (tests/test_dag.py).
"""

from datetime import datetime, timedelta, timezone

from airflow import DAG
from airflow.operators.python import ShortCircuitOperator
from cloudera.cdp.airflow.operators.cde_operator import CDEJobRunOperator

JOB_PREFIX = "rsingh-mcc"
DB_PREFIX = "rsingh_mcc"
CHECKPOINTS = "s3a://federal-buk-574bcea0/data/IB/rsingh_mcc/checkpoints"
LIVE_DATES = ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24",
              "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29",
              "2026-10-30")   # lakehouse.json "scheduled_dates"
LIVE_START_UTC = "03:30"                                   # streaming.json live_window
LIVE_STOP_UTC = "13:30"
MIN_SECONDS = 300
PRODUCER_LEAD_S = 120


def live_window(dag_run, data_interval_end, ti, **_) -> bool:
    now = datetime.now(timezone.utc)
    day = data_interval_end if dag_run.run_type == "scheduled" else now
    if day.strftime("%Y-%m-%d") not in LIVE_DATES:
        print(f"{day:%Y-%m-%d} is not a live date {LIVE_DATES}: nothing to stream")
        return False
    h, m = map(int, LIVE_STOP_UTC.split(":"))
    stop = datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc)
    seconds = int((stop - now).total_seconds())
    if seconds < MIN_SECONDS:
        print(f"live window ended at {stop:%Y-%m-%d %H:%M} UTC: nothing to stream")
        return False
    print(f"streaming until {stop:%Y-%m-%d %H:%M} UTC ({seconds} s)")
    ti.xcom_push(key="stream_s", value=seconds)
    ti.xcom_push(key="producer_s", value=max(seconds - PRODUCER_LEAD_S, 60))
    return True


with DAG(
    dag_id="mcc_live_stream",
    description="Live Kafka stream into bronze during the demo day, stopped before the nightly batch",
    schedule_interval=f"{int(LIVE_START_UTC[3:])} {int(LIVE_START_UTC[:2])} * * *",
    # the first run starts on 10-19 03:30 UTC (end of the 10-18 interval), the last on 10-30
    start_date=datetime(2026, 10, 18, 3, 30),
    end_date=datetime(2026, 10, 29, 3, 30),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=11),
    # a retry would restart a window that has already been used; both jobs stop themselves
    default_args={"owner": "claims-data", "retries": 0, "execution_timeout": timedelta(hours=11)},
    tags=["streaming", "kafka", "insurance"],
) as dag:
    window = ShortCircuitOperator(task_id="live_window", python_callable=live_window)
    xcom = "{{ ti.xcom_pull(task_ids='live_window', key='%s') }}"
    stream = CDEJobRunOperator(
        task_id="stream_bronze", job_name=f"{JOB_PREFIX}-stream-bronze", wait=True,
        overrides={"spark": {"args": ["--db-prefix", DB_PREFIX, "--checkpoints", CHECKPOINTS,
                                      "--starting-offsets", "earliest", "--await-seconds", xcom % "stream_s"]}})
    produce = CDEJobRunOperator(
        task_id="stream_produce_live", job_name=f"{JOB_PREFIX}-stream-produce", wait=True,
        overrides={"spark": {"args": ["--mode", "live", "--duration", xcom % "producer_s"]}})
    window >> [stream, produce]
