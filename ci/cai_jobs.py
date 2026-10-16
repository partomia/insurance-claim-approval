"""
The CAI jobs of this project: one definition read by ci/setup_cai.py (creates them) and
ci/trigger_cai_pipeline.py (runs and follows them). Pure Python, so the GitHub runner can import
it without cmlapi. Copied from O-G-Asset-Integrity-Lakehouse (from CXR) and adapted.

The chain mcc-00 -> 01 -> 02 -> 03 -> 04 runs through CAI job dependencies: a dependent job
starts only when its parent succeeds, which makes the KPI gate's exit code a hard stop. Jobs 02-04
work on both heads (MCC_MODEL=all): approval and fraud are trained, gated and deployed together
behind the one endpoint mcc-approval.
  mcc-00-sync-code      the repo is private and the project blank: ci/push_files.py uploads the
                        code; this job installs requirements.txt and checks CODE_VERSION
  mcc-05-nightly-drift  02:00: the latest claims through the guardrails and the champion, PSI drift
  mcc-06-score-claims   one business date of claims into gold.fact_model_score (shadow scores);
                        started by the lakehouse DAG (cde/dags/mcc_dag.py) or by hand
  mcc-07-promote-champion  manual, named approver: the app's model mode (shadow -> assist)
  mcc-08-retrain-trigger   02:30: starts mcc-01 on drift, new labels or a stale champion
Sizes: 1 vCPU / 4 GB fits beside the endpoint and app on the shared federal quota.
"""
from __future__ import annotations

import json
import os

RUNTIME = "docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-pbj-jupyterlab-python3.11-standard:2026.08.1-b5"
ALL = {"MCC_MODEL": "all"}

JOBS = [
    {"name": "mcc-00-sync-code", "script": "ci/sync_code.py", "parent": None,
     "cpu": 2, "memory": 8, "timeout": 3600, "schedule": None},
    {"name": "mcc-01-build-features", "script": "features/build_feature_table.py", "parent": "mcc-00-sync-code",
     "cpu": 1, "memory": 4, "timeout": 3600, "schedule": None},
    {"name": "mcc-02-train-validate", "script": "train/train_validate.py", "parent": "mcc-01-build-features",
     "cpu": 1, "memory": 4, "timeout": 3600, "schedule": None, "env": ALL},
    {"name": "mcc-03-kpi-gate", "script": "gate/kpi_gate.py", "parent": "mcc-02-train-validate",
     "cpu": 1, "memory": 4, "timeout": 600, "schedule": None, "env": ALL},
    {"name": "mcc-04-deploy-champion", "script": "serve/deploy_champion.py", "parent": "mcc-03-kpi-gate",
     "cpu": 1, "memory": 4, "timeout": 5400, "schedule": None, "env": ALL},
    {"name": "mcc-05-nightly-drift", "script": "monitor/drift.py", "parent": None,
     "cpu": 1, "memory": 4, "timeout": 3600, "schedule": "0 2 * * *"},
    {"name": "mcc-06-score-claims", "script": "lakehouse/score_claims.py", "parent": None,
     "cpu": 1, "memory": 4, "timeout": 3600, "schedule": None},
    {"name": "mcc-07-promote-champion", "script": "serve/promote_champion.py", "parent": None,
     "cpu": 1, "memory": 4, "timeout": 600, "schedule": None},
    {"name": "mcc-08-retrain-trigger", "script": "ci/retrain_trigger.py", "parent": None,
     "cpu": 1, "memory": 4, "timeout": 600, "schedule": "30 2 * * *"},
    # any script with its output in outputs/logs/ (set MCC_RUN_SCRIPT on the job; ci/run_logged.py --fetch)
    {"name": "mcc-99-debug", "script": "ci/run_logged.py", "parent": None,
     "cpu": 1, "memory": 4, "timeout": 3600, "schedule": None, "env": {"MCC_RUN_SCRIPT": "ci/sync_code.py"}},
]

CHAIN = ["mcc-00-sync-code", "mcc-01-build-features", "mcc-02-train-validate", "mcc-03-kpi-gate",
         "mcc-04-deploy-champion"]
GATE_JOB = "mcc-03-kpi-gate"
SCORE_JOB = "mcc-06-score-claims"
PROMOTE_JOB = "mcc-07-promote-champion"
FIRST_TRAINING_JOB = "mcc-01-build-features"


def resolve_runtime(client, configured: str = "") -> str:
    """The runtime image for jobs and model builds: the configured one, else the runtime of the
    current session/job (matched on the ML_RUNTIME_* variables CAI sets)."""
    if configured:
        return configured
    wanted = {k: os.environ.get(f"ML_RUNTIME_{k.upper()}") for k in ("kernel", "edition", "editor")}
    if not all(wanted.values()):
        return RUNTIME
    found, token = [], None
    while True:   # the API pages its results: the session's runtime can be past the first page
        kw = {"page_token": token} if token else {}
        resp = client.list_runtimes(search_filter=json.dumps(wanted), page_size=100, **kw)
        found += list(resp.runtimes or [])
        token = getattr(resp, "next_page_token", None)
        if not token:
            break
    full = os.environ.get("ML_RUNTIME_FULL_VERSION")
    exact = [r for r in found if full and getattr(r, "full_version", None) == full]
    pick = (exact or sorted(found, key=lambda r: getattr(r, "full_version", "") or ""))
    return pick[-1].image_identifier if pick else RUNTIME
