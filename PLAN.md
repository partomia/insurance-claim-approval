Motor Claim Copilot on Cloudera — Build Plan
Oct 16, 2026 · @RAVI

## Overview

**The claim the demo proves.** One governed Cloudera platform can run an insurer's
motor-claims operation end to end: policy, customer and claims data land in an Iceberg
lakehouse, live claim and telematics events stream in through Kafka, gold tables feed
a trained approval/fraud model on CAI, and the model's second opinion reaches the
adjudicator inside the existing Motor Claim Copilot app, with the KPIs, lineage and
masking an insurer's regulator asks for.

**The story.** A synthetic Indian motor insurer (about 800 historical policies, 60 in
the active book, 40 network garages, 800 customers) files about 40 new claims a day.
The policy-admin system, the claims system, a credit/driving bureau and the garage
network each deliver files daily; the Copilot app and the vehicles' telematics units
publish events in real time. Today every decision is hand-written rules (fraud signal
weights, trust tiers, thresholds).

**The decision supported.** Routing: does a claim go straight through (auto-approve)
or to a human adjuster / fraud review? The model predicts `p_approve` and
`p_fraud_review` with top factors and runs in **shadow mode** (shown to insurers and
experts, logged, never changes an outcome). **What the model does NOT decide:** it
never rejects a claim, never blocks or sizes a payout, and is never shown to the
customer. Any later "route" mode can only send a claim *to* review, never away from it.

**Scale.** 5 backfilled business dates plus scheduled dates; ~4,000 historical claims,
~40 claims/day, ~2 telematics events/second while the producer runs. A full run takes
minutes on the cluster and runs on a laptop for CI. All data is synthetic, plus one
pinned public claims-fraud table used only as an external benchmark for the fraud head.

## End-to-end flow

```
generators/ (seeded)  ──>  S3 landing/<source>/<date>/ + _manifest.json
                                │  CDE  rsingh-mcc-stages (land → bronze → silver → mdm → gold → recon)
Copilot app ── claim events ─┐  │                       Airflow DAG rsingh-mcc-orchestration
telematics producer (CDE) ───┴> Kafka mcc.claim.events / mcc.telematics.crash
                                │  CDE streaming  rsingh-mcc-stream-bronze
                                ▼
                rsingh_mcc_{bronze,silver,mdm,gold,ref}  (Iceberg v2)
                     │                          │
       CDW Impala semantic views         CAI jobs mcc-00..08 (features → train → gate →
       Data Visualization dashboards     registry → endpoint → batch score → drift)
                     │                          │
                     └────── Copilot app (FastAPI + React, CAI Application) ──────┘
                             lakehouse ingest ← gold · shadow model card · Model vs rules
```

## Requirements map

| # | Requirement (skill phase) | Where it is met |
|---|---|---|
| 1 | Synthetic sources + one pinned public set | `generators/` (policy admin, claims, bureau, garage network, CDC), `scripts/fetch_dataset.py` |
| 2 | Landing with manifests, planted faults | `cde/jobs/land_sources.py`, `generators/faults.py`, `contracts/` |
| 3 | Bronze, quarantine, load_audit, recon | `cde/jobs/ingest_bronze.py`, `cde/jobs/reconcile.py`, `ref.load_audit`, `ref.recon_results` |
| 4 | Kafka + CDE streaming | `stream/producer/`, `cde/jobs/stream_produce.py`, `cde/jobs/stream_bronze.py`, topics `mcc.*` |
| 5 | Silver, master data, gold with SCD2 | `cde/jobs/build_silver.py`, `build_mdm.py` (golden customer + vehicle), `build_gold.py` |
| 6 | CDE live + Airflow | `cde/dags/mcc_dag.py`, `cde/scripts/deploy_*.sh`, `cde/jobs/run_stages.py` |
| 7 | CDW semantic layer + KPI consistency | `sql/semantic/*.sql`, `scripts/run_semantic.py`, `config/kpi.json` |
| 8 | Data Visualization as code | `dataviz/build_dashboard.py`, `dataviz/mcc_dashboards.json` (PKs 14000+) |
| 9 | CAI ML chain + AI Registry + endpoint | `features/`, `train/`, `gate/`, `serve/`, `ci/cai_jobs.py`, jobs `mcc-00..08` |
| 10 | Guardrails, MLOps loop, app | `guardrails/`, `config/guardrails.yaml`, `monitor/drift.py`, Copilot app shadow integration |
| 11 | Governance | `config/governance.json`, `scripts/governance.py` (Atlas + Ranger) |
| 12 | Ops | `scripts/platform_ctl.py`, `config/platform.json`, `docs/DEMO_RUNBOOK.md` |
| 13 | CI | `.github/workflows/ci.yml` (offline chain), `cai-mlops.yml` (GitHub → CAI API v2) |

## Platform mapping (environment `federal-cdp-env`, same as the sibling demos)

| Layer | Service | What runs there |
|---|---|---|
| Landing + raw files | S3 `federal-buk-574bcea0` | `data/IB/rsingh_mcc/landing/<source>/<date>/` |
| Stream transport | Kafka Data Hub `federal-kafka`, Schema Registry, SMM | topics `mcc.claim.events`, `mcc.telematics.crash`, `mcc.control` |
| Batch + streaming Spark | CDE `federal-cde` / `federal-cde-vc` | `rsingh-mcc-*` jobs, `rsingh-mcc-orchestration` DAG |
| Semantic layer | CDW `federal-impala-1` | `rsingh_mcc_semantic` views, Hue ad-hoc + time travel |
| Dashboards | Data Visualization (existing CDW instance used by siblings) | `MCC ...` dashboards |
| ML + app | CAI workspace `federal-cml-ws` | project `rsingh-motor-claim-copilot`, jobs, model, AI Registry, Application |
| Governance | SDX data lake (Atlas, Ranger) | `MCC_SENSITIVE_*`, `rsingh-mcc-*` policies |

## Names and conventions

- Short code **`mcc`** (Motor Claim Copilot); checked free in CAI and CDE on 2026-10-16.
- Databases `rsingh_mcc_{bronze,silver,mdm,gold,semantic,ref}`.
- CDE: files resource `rsingh-mcc-code` (private repo → built from `git archive` of a
  pushed commit), jobs `rsingh-mcc-{stages,land,bronze,silver,mdm,gold,recon}`,
  `rsingh-mcc-stream-{produce,bronze}`, DAG `rsingh-mcc-orchestration`.
- CAI: project `rsingh-motor-claim-copilot`; jobs `mcc-00-sync-code`,
  `mcc-01-build-features`, `mcc-02-train-validate`, `mcc-03-kpi-gate`,
  `mcc-04-deploy-champion`, `mcc-05-nightly-drift`, `mcc-06-score-claims`,
  `mcc-07-promote-champion`, `mcc-08-retrain-trigger`, `mcc-lakehouse-ingest`,
  `mcc-export-claims`; model `mcc-approval`; registry models `mcc-approval`,
  `mcc-fraud`; application `MCC Motor Claim Copilot`.
- Env vars `MCC_*` (laptop/CI) in a git-ignored root `.env`; the app keeps
  `backend/.env` (its own settings, already git-ignored).
- Data Visualization objects `MCC ...`, primary keys 14000–14999 (siblings use 7000–13599).
- Atlas `MCC_SENSITIVE_PII`, `MCC_SENSITIVE_FINANCIAL`; glossary `MCC Claims KPIs`;
  Ranger `rsingh-mcc-*`.

**Existing deployments are left alone.** The go01 env 1 CDE jobs (`rsingh-insurance-*`)
mount `cde/jobs/{generate,validate,transform,curate}/` from `main`, and env 2 (AWC,
OLTP-only) tracks `main`. No existing file under those paths is moved or removed;
every new app feature is off by default (`LAKEHOUSE_*`, `APPROVAL_MODEL_MODE=off`).
Work happens on branch `feature/cloudera-mcc`, merged to `main` at the end.

## Synthetic sources

One seeded universe (`generators/universe.py`) so every claim, bureau row, garage and
event points at a policy/customer/vehicle that exists. Logic is ported from the current
CDE generators (`generate_bronze.py`, `generate_claims_bronze.py`,
`generate_customer_profile_bronze.py`) into plain Python so the laptop, CI and CDE share it.

| Source | Type | Format | Generator | Cadence |
|---|---|---|---|---|
| Policy admin (policies, clauses) | structured | CSV full day 1, then CDC JSON (endorsements, renewals, lapses) | `gen_policy_admin.py` | full, then daily |
| Claims system (FNOL + status history) | structured | JSON lines | `gen_claims.py` | daily ~40 + 4,000 history |
| Credit / driving bureau | structured | pipe-delimited with trailer count | `gen_bureau.py` | daily refresh |
| Garage network master | reference | CSV | `gen_garages.py` | day 1, then changes |
| App claim events | streaming | JSON on `mcc.claim.events` | Copilot app publisher (off by default) + producer replay | live |
| Telematics crash events | streaming | JSON on `mcc.telematics.crash` | `stream/producer/telematics_producer.py` | live, ~2/s |

**Outcomes made learnable** (the blocker in `docs/plans/step5-approval-model-plan.md`):
claim status and a `fraud_confirmed` label are drawn from a logistic function of latent
risk (garage risk, amount outlier, claim frequency, customer care, telematics
corroboration) plus noise, keeping the mix near today's 60/15/15/10.

**Planted faults:** duplicate claim re-sent, a bureau file whose trailer count is off by
one, a CDC change for an unknown policy, a customer under two spellings + phones (MDM
work), a claim whose VIN does not match the policy, a late telematics event, an
out-of-order status update.

## Layers and model

- **Bronze:** as received plus `_batch_id, _business_date, _source_system, _source_file,
  _record_hash`; `quarantine` with reason codes; `stream_claim_event`, `stream_telematics`.
- **Silver:** typed, deduped; CDC applied with MERGE; claim status history.
- **MDM (`rsingh_mcc_mdm`):** `customer_candidate`, `match_pair`, `customer_xref`,
  `golden_customer`; `vehicle_xref` (VIN ↔ registration ↔ policy).
- **Gold:** `dim_date`, `dim_customer` (SCD2), `dim_policy` (SCD2), `dim_vehicle`,
  `dim_garage`, `fact_claim`, `fact_claim_status`, `fact_telematics_event`,
  `claim_training_features` (point-in-time), `fact_model_score`, and the app-facing
  tables the Copilot already ingests: `policy_master`, `policy_clauses`,
  `policy_risk_signals`, `garage_risk_signals`, `customer_profile_signals`.
- **Ref:** `load_audit`, `recon_results`, `dq_results`, `kpi_definition`,
  `model_event`, `guardrail_event`.

**Certified KPIs** (one Impala view each in `rsingh_mcc_semantic`, a `ref.kpi_definition`
row and a glossary term; a consistency check proves consumers agree):

| KPI | Definition |
|---|---|
| Straight-through rate | Share of decided claims with no human review, by day and claim type |
| Claim cycle time | Hours FNOL → decision, median and P90, auto vs reviewed |
| Loss ratio | Approved claim amount / earned premium, by policy segment and month |

## ML

- **Heads:** `approval` (APPROVED vs REJECTED) and `fraud` (`fraud_confirmed`), scikit-learn
  `HistGradientBoostingClassifier` (no new heavy deps), time-based split.
- **One feature definition:** `features/feature_logic.py` is used by the CDE training-table
  build, CAI training, the endpoint and the app's `approval_model_service.py`;
  `feature_hash()` locks them together (the endpoint refuses a mismatch).
- **Threshold rule:** review threshold set on VAL; KPIs measured on TEST only.
- **Gate (`mcc-03`):** approval AUC ≥ 0.75, fraud PR-AUC ≥ 2× base rate, calibration
  (Brier) and non-regression vs the champion; exit non-zero stops the chain.
- **Registry:** a version of `mcc-approval` / `mcc-fraud` per passed candidate, registered
  before the endpoint deploy; stage and approver kept in `ref.model_event` (registry tags
  are not stored). Champion = endpoint `mcc-approval` serving both heads with top factors.
- **Batch:** `mcc-06` scores each business date into `gold.fact_model_score`;
  `mcc-05` PSI drift; `mcc-08` weekly retrain trigger; `mcc-07` promotion with a named approver.
- **Public benchmark:** `fraud_oracle.csv` ("carclaims", Angoss; Kaggle
  `shivamb/vehicle-claim-fraud-detection`, **CC0 public domain**, 15,420 claims, 923 fraud),
  fetched from a URL pinned to a commit and checked by sha256 (`scripts/fetch_dataset.py`).
  It evaluates the fraud head's method out of domain and is never mixed into training.

## Guardrails

| Layer | Guardrail | Code | When it fires |
|---|---|---|---|
| Input | File and message contracts | `contracts/`, `ingest_bronze.py`, `stream_bronze.py` | Row to quarantine, never scored |
| Input | Feature range / OOD check vs training | `guardrails/input_checks.py` | Model abstains (`UNCERTAIN`), rules unchanged |
| Input | Customer not resolved by MDM / no profile | `input_checks.py` | Scored without profile features, flagged |
| Output | Never reject, never customer-visible | `guardrails/output_policy.py`, app routers | Prediction stripped from customer APIs |
| Output | Abstain band around the threshold | `output_policy.py` | Shown as "uncertain" |
| Process | KPI gate + non-regression, feature-hash lock | `gate/kpi_gate.py`, `serve/predict.py` | Chain stops, champion keeps serving |
| Process | Named approver for promotion / route mode | `serve/promote_champion.py` | `PROMOTION_REFUSED` without evidence |
| Process | Drift (PSI), `TOO_FEW` below 30 | `monitor/drift.py` | Guardrail event + dashboard flag |
| LLM | Reasoning grounded in the rule that fired; PII kept out of prompts | existing `llm_service.py` + `guardrails/llm_guard.py` | Template fallback |

All events land in `ref.guardrail_event`.

## Application

The existing Motor Claim Copilot (FastAPI + React) is the application, deployed as a
CAI Application on federal (`cml/run.py`); no separate Streamlit app.
- Claim Insights (insurer/expert only): **Model view** card — p_approve, p_fraud_review,
  top factors, agrees/disagrees with the rules decision, model version.
- Insurer dashboard: **Model vs rules** panel — agreement rate and disagreements to review.
- Existing Book of Business, trust card and lakehouse risk card read the new gold tables.
- Optional (off by default): claim events published to `mcc.claim.events`.

## Phases (one commit each, `pytest -q` green first)

- ☐ 0 Discovery: platform names, short code, public dataset + licence
- ☐ 1 PLAN.md + approval list (this file)
- ☐ 2 Scaffold: config/, contracts/, .env.example, .gitignore, hooks, tests, local runner
- ☐ 3 Generators + landing (manifests, planted faults, learnable outcomes)
- ☐ 4 Bronze / quarantine / load_audit, recon at bronze
- ☐ 5 Streaming: producer, topics + schemas, CDE streaming job, stream recon
- ☐ 6 Silver, MDM, gold (SCD2, training features, app-facing tables), recon per layer
- ☐ 7 CDE live: files resource, jobs, Airflow DAG, one date end to end
- ☐ 8 CDW semantic views + KPI consistency; Data Visualization dashboards
- ☐ 9 CAI: project, env, jobs 00–08, endpoint, AI Registry
- ☐ 10 Guardrails, MLOps loop, Copilot app on federal (shadow mode)
- ☐ 11 Governance: Atlas classifications + glossary, Ranger tag masking
- ☐ 12 Ops: platform_ctl.py, runbooks, README status, merge to main

## How we work

- Copy from the siblings first (GDL lakehouse spine, CXR ML chain, OGX streaming/DAG/
  platform code) and adapt; every copied file gets a row in `docs/REUSE_INVENTORY.md`.
  Siblings are never edited.
- Credentials come from the siblings' local `.env` files, re-prefixed `MCC_*` into this
  repo's git-ignored `.env`; values are never printed or committed.
- One approval list up front; anything destructive, outside the `mcc` prefix or on
  shared services asks again. Every live action goes to `docs/PROJECT_LOG.md`.

## Decisions / open items

- Repo stays **private**: CDE uses a files resource from `git archive`; the CAI project is
  created blank and code is pushed with `ci/push_files.py` (CXR/OGX pattern).
- Kafka brokers are closed from the laptop: topics are created and events produced
  from CDE (OGX pattern).
- LLM for the app on federal: no Groq / AI Inference key exists in any local `.env`. The
  app runs with its deterministic fallback until one is added to the CAI project's
  `backend/.env`.
- Masked demo users for Ranger: reuse `federal01` (masked) and `federal07` (unmasked) as OGX does.
