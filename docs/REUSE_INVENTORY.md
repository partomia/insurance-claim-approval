# Reuse inventory

Every file copied from a sibling repository, what it came from and what changed. Siblings:
OGX = O-G-Asset-Integrity-Lakehouse, GDL = General-DataLakehouse, CXR = the chest X-ray project.

| File here | Copied from | Changes |
|---|---|---|
| `cde/jobs/mcc_common.py` | OGX `cde/jobs/ogx_common.py` (GDL `gdl_common.py`) | layers `mdm` instead of `asset`; `MCC_` env vars; mysqldump parser and tag normaliser removed; CSV parser added |
| `cde/jobs/ingest_bronze.py` | OGX `cde/jobs/ingest_bronze.py` (record path) | object/document ingest removed; CSV format; manifest-missing check on policy_admin and claims |
| `cde/jobs/land_sources.py` | OGX `cde/jobs/land_sources.py` | generators are `generators.universe.World` + `generators.landing.files_for` |
| `cde/jobs/run_stages.py` | OGX `cde/jobs/run_stages.py` | stage list (land, bronze, silver, mdm, gold, recon) |
| `scripts/run_local.py` | OGX `scripts/run_local.py` (GDL) | stage list; one streaming job; `MCC_` env vars |
| `common.py` | OGX `common.py` | `MCC_ROOT`, `MCC_MODEL` (default approval), `MCC_CONFIG_OVERLAY` |
| `config/pipeline.yaml` | OGX `config/pipeline.yaml` (CXR) | tabular approval and fraud heads; time-based split; gate per head |
| `config/guardrails.yaml` | OGX `config/guardrails.yaml` | claim-level input checks; shadow-mode output rules; fairness slices |
| `config/platform.json` | OGX `config/platform.json` | mcc project workloads; no NiFi or Flink |
| `config/streaming.json` | OGX `config/streaming.json` | three mcc topics; no NiFi block |
| `config/kpi.json` | OGX `config/kpi.json` (format) | STP, claim cycle time, loss ratio |
| `contracts/*.json` | GDL `contracts/*.json` (format) | insurer entities |
| `scripts/install_hooks.sh`, `scripts/hooks/*` | OGX (GDL) | wording only |
| `.env.example` | OGX `.env.example` | `MCC_` names; Groq |
| `tests/conftest.py` | OGX `tests/conftest.py` | `MCC_CONFIG_OVERLAY` |
| `cde/jobs/reconcile.py` | OGX `cde/jobs/reconcile.py` (GDL) | object checks removed; mcc stream tables; silver, mdm and gold checks are mcc-specific |
| `stream/producer/claim_producer.py` | OGX `stream/producer/sensor_producer.py` | crash and claim events from the seeded universe; per-topic minute control counts |
| `stream/producer/topics.py` | OGX `stream/producer/topics.py` | mcc topics and schemas; no NiFi topic |
| `cde/jobs/stream_produce.py` | OGX `cde/jobs/stream_produce.py` | claim producer; files sink passthrough |
| `cde/jobs/stream_bronze.py` | OGX `cde/jobs/stream_telemetry_bronze.py` | tables from the stream contracts |
| `cde/scripts/mcc_deploy_jobs.sh`, `mcc_deploy_streaming.sh`, `mcc_deploy_dag.sh` | OGX `cde/scripts/deploy_*.sh` | files resource rsingh-mcc-code (private repo); mcc stages; the go01 `deploy_jobs.sh` and `deploy_dag.sh` are untouched |
| `cde/scripts/mcc_deploy_code.sh` | new | `git archive` of a pushed commit to the files resource, CODE_VERSION inside |
| `cde/dags/mcc_dag.py` | OGX `cde/dags/ogx_dag.py` | mcc stages; created paused |
| `cde/jobs/build_silver.py`, `build_mdm.py`, `build_gold.py` | new (structure after OGX build_*.py) | insurer silver, MDM, gold, app tables with the columns of `cde/jobs/curate/*` |
| `scripts/run_semantic.py` | O-G-Asset-Integrity-Lakehouse `scripts/run_semantic.py` | engines, renderer, results writer kept; check/adhoc rewritten for STP, CCT, LR |
| `dataviz/build_dashboard.py` | O-G-Asset-Integrity-Lakehouse `dataviz/build_dashboard.py` | export/import/verify machinery unchanged; datasets, sheets, dashboards and PKs (14000+) new |
| `sql/semantic/50_dashboard_views.sql` (`dash_recon`, `dash_load_audit`) | O-G-Asset-Integrity-Lakehouse `sql/semantic/50_dashboard_views.sql` | layer labels add mdm and gold |
| `lakehouse/store.py`, `lakehouse/publish.py` | O-G-Asset-Integrity-Lakehouse | adapted: MCC_ prefix, model_event KPI columns (pr_auc, base_rate), version id includes the head |
| `guardrails/events.py`, `guardrails/input_checks.py`, `guardrails/output_policy.py` | O-G-Asset-Integrity-Lakehouse | adapted: claim checks (policy/customer resolved, missing features, amount range), NaN-aware OOD, approval/fraud bands |
| `train/train_validate.py`, `gate/kpi_gate.py` | O-G-Asset-Integrity-Lakehouse | adapted: tabular heads, calibrated gradient boosting, PR-AUC lift gate, both heads per job |
| `serve/predict.py`, `serve/registry.py`, `serve/deploy_champion.py` | O-G-Asset-Integrity-Lakehouse (from CXR) | adapted: two heads behind one endpoint mcc-approval |
| `monitor/drift.py`, `ci/retrain_trigger.py` | O-G-Asset-Integrity-Lakehouse | adapted: claims via the batch scoring path; new labels = newly decided claims |
| `ci/cai_jobs.py`, `ci/setup_cai.py`, `ci/push_files.py`, `ci/sync_code.py` | O-G-Asset-Integrity-Lakehouse (from CXR) | adapted: blank project for a private repo, CODE_VERSION written by the push |
| `scripts/governance.py` | O-G-Asset-Integrity-Lakehouse (from GDL) | adapted: MCC_ tag prefix, MCC_WORKLOAD_* credentials; `config/governance.json` new (claims PII, bureau score, VIN) |
| `scripts/platform_ctl.py`, `.cursor/rules/project-start-stop.mdc` | O-G-Asset-Integrity-Lakehouse | adapted: no NiFi or Flink layers; MCC_* credentials, mcc_deploy_streaming.sh; `config/platform.json` (Phase 2 scaffold) gains the cron per CAI schedule |
| `cde/scripts/set_airflow_variables.py`, `cai_score_claims` in `cde/dags/mcc_dag.py` | Chest-X-ray-Triage | adapted: MCC_CAI_* variables, mcc-06-score-claims with MCC_BUSINESS_DATE |
| `ci/trigger_cai_pipeline.py`, `.github/workflows/cai-mlops.yml`, `.github/workflows/ci.yml` | O-G-Asset-Integrity-Lakehouse (from CXR) | adapted: the runner pushes files (push_files.py, CODE_VERSION) before the chain; CI adds backend tests and the SPA build |
