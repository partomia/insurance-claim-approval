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
