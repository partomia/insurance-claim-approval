"""
Airflow DAG — orchestrates the insurance policy + claims-analytics medallion
pipeline on CDE.

Job execution order:
  generate-bronze -> validate-bronze -> transform-silver -> curate-gold
    -> generate-claims-bronze -> validate-claims-bronze -> transform-claims-silver
    -> curate-risk-signals-gold

The claims/risk-signals half runs after curate-gold because
curate_risk_signals_gold.py's analytics (fraud score, peer benchmarks) are
the actual "datalakehouse speciality" payoff of this pipeline -- computed
over a much larger synthetic claims-history population (~800 policies) than
policy_master's ~60 active rows, precisely so the percentiles/benchmarks are
statistically meaningful. See cde/README.md for the full design writeup.

Uses CDEJobRunOperator to trigger CDE Spark jobs by name (same mechanism as
Cloudera-CDE-Workshop-with-Orchestration-and-CI-CD/dags/etl_pipeline_dag.py).

Manual-trigger by default (schedule_interval=None) since this is a demo/
validation pipeline, not a continuously-arriving-data pipeline. Flip
schedule_interval to e.g. "@daily" once you're ready to run it on a cadence.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Variable
from cloudera.cdp.airflow.operators.cde_operator import CDEJobRunOperator

# Optional: override the synthetic row counts without redeploying the jobs.
#   airflow variables set INSURANCE_N_POLICIES "120"
#   airflow variables set INSURANCE_N_CLAIMS "6000"
N_POLICIES = Variable.get("INSURANCE_N_POLICIES", default_var="60")
N_CLAIMS = Variable.get("INSURANCE_N_CLAIMS", default_var="4000")

default_args = {
    "owner": "insurance-claim-lakehouse",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="insurance_lakehouse_pipeline",
    description="Insurance policy medallion pipeline: generate -> validate -> transform -> curate",
    default_args=default_args,
    schedule_interval=None,  # manual trigger; set to "@daily" etc. when ready
    start_date=datetime(2025, 1, 1),
    catchup=False,
    is_paused_upon_creation=False,
    tags=["insurance", "iceberg", "medallion"],
) as dag:

    # NOTE: job_name must exactly match the CDE Job names created by
    # cde/scripts/deploy_jobs.sh. Those use an `rsingh-` prefix to avoid
    # collisions on this shared vcluster -- if you deploy under a different
    # user/prefix, update both deploy_jobs.sh and these job_name values
    # together, or CDEJobRunOperator will fail with a 404 "job not found".
    generate = CDEJobRunOperator(
        task_id="generate_bronze",
        job_name="rsingh-insurance-generate-bronze",
        overrides={"spark": {"args": [N_POLICIES]}},
        wait=True,
    )

    validate = CDEJobRunOperator(
        task_id="validate_bronze",
        job_name="rsingh-insurance-validate-bronze",
        wait=True,
    )

    transform = CDEJobRunOperator(
        task_id="transform_silver",
        job_name="rsingh-insurance-transform-silver",
        wait=True,
    )

    curate = CDEJobRunOperator(
        task_id="curate_gold",
        job_name="rsingh-insurance-curate-gold",
        wait=True,
    )

    generate_claims = CDEJobRunOperator(
        task_id="generate_claims_bronze",
        job_name="rsingh-insurance-generate-claims-bronze",
        overrides={"spark": {"args": [N_CLAIMS]}},
        wait=True,
    )

    validate_claims = CDEJobRunOperator(
        task_id="validate_claims_bronze",
        job_name="rsingh-insurance-validate-claims-bronze",
        wait=True,
    )

    transform_claims = CDEJobRunOperator(
        task_id="transform_claims_silver",
        job_name="rsingh-insurance-transform-claims-silver",
        wait=True,
    )

    curate_risk_signals = CDEJobRunOperator(
        task_id="curate_risk_signals_gold",
        job_name="rsingh-insurance-curate-risk-signals-gold",
        wait=True,
    )

    generate >> validate >> transform >> curate
    curate >> generate_claims >> validate_claims >> transform_claims >> curate_risk_signals
