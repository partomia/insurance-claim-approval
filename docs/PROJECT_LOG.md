# Project log — Motor Claim Copilot on Cloudera (`mcc`)

Every live action, run id, count and plan change, newest last. No secret values.
Earlier history of this repo (go01 env 1, AWC env 2) is in `MEMORY_DUMP.md`.

## 2026-10-16 12:10 - Discovery (read-only)

- **Target environment** `federal-cdp-env`, same as the sibling demos (OGX, CXR):
  CAI workspace `federal-cml-ws` (`https://federal-cml.federal.dp5i-5vkq.cloudera.site`),
  CDE `federal-cde` / `federal-cde-vc` (local `~/.cde/config.yaml` already points at it,
  CLI 1.23.0), CDW `federal-impala-1`, Kafka Data Hub `federal-kafka`, bucket
  `federal-buk-574bcea0`. Connection details taken from `O-G-Asset-Integrity-Lakehouse/.env`
  (names only read here).
- **CAI** projects listed: 11, none with `mcc`. **CDE** jobs listed: 54, prefixes
  casa/churn/coll/cxr/gdl/mule/ogx/spend; no `mcc`.
- **Data Visualization** primary keys in use by siblings: 7000–13599 → `mcc` takes 14000+.
- **GitHub** `partomia/insurance-claim-approval` is **private** → CDE files resource from
  `git archive`, blank CAI project + file push (CXR/OGX pattern).
- **Plan change: target environment.** Earlier work ran on go01 (env 1, `rsingh-insurance-*`,
  `insurance_lakehouse*`) and AWC (env 2, OLTP only). The use case is now built on
  federal under the `mcc` prefix; the go01/AWC deployments and their files on `main`
  are left untouched.
- No LLM key (Groq / AI Inference) exists in any local `.env`; the app on federal starts
  with its deterministic fallback until one is supplied.
- Public dataset chosen: `fraud_oracle.csv` (carclaims), CC0, 15,420 rows.
- `PLAN.md` written; branch `feature/cloudera-mcc`.

## 2026-10-16 13:00–14:00 - Phases 2–6 (local only)

- Scaffold, contracts, generators with planted faults, bronze/quarantine/recon, streaming producer
  and Spark stream leg, silver, MDM (863 refs → 800 golden, 63 merged, all bureau-linked), gold
  (SCD2 dims, fact_claim, point-in-time training features, scoring context, Copilot app tables).
- Local end to end for 2026-10-12..16 clean except the planted bureau trailer MISMATCH on 2026-10-14.
- Learnability on gold features: approval AUC 0.81; fraud AUC 0.94, PR-AUC 0.61 (base rate 0.054).
- Fix: an earlier commit overwrote go01's `cde/scripts/deploy_jobs.sh` / `deploy_dag.sh`; both
  restored from `main`, the mcc scripts are `cde/scripts/mcc_deploy_*.sh`.

## 2026-10-16 14:20 - Phase 7: CDE live (federal-cde-vc)

- Files resource `rsingh-mcc-code` created from `git archive` of HEAD (61 files + CODE_VERSION).
- Jobs created: `rsingh-mcc-{land,bronze,silver,mdm,gold,recon,stages}` (driver 2c/4g,
  executors 4c/8g, 1–4 executors). No python-env resource needed.
- Run **643** `rsingh-mcc-stages` land→recon for 2026-10-12: **succeeded** in 5 min.

## 2026-10-16 14:57 - Phase 8 code; CDE all dates; streaming

- Semantic layer: certified views `kpi_straight_through_rate`, `kpi_claim_cycle_time`,
  `kpi_loss_ratio`, MIS and dashboard views; gold `fact_policy_month`. Local consistency check
  8/8 MATCHED per date. Loss ratio ~570%: the synthetic book is claim-dense by design (≈4,000
  claims on 863 policies to give the models enough training rows); the figure is reported as is.
- Resource `rsingh-mcc-code` re-uploaded at `83a1197`.
- Run **644** `rsingh-mcc-stages` land→recon for 2026-10-12..16.
- Jobs created: `rsingh-mcc-stream-bronze`, `rsingh-mcc-stream-produce`.
- Run **645** `rsingh-mcc-stream-produce --setup --mode backfill` (topics `mcc.claim.events`,
  `mcc.telematics.crash`, `mcc.control`, 3 partitions, 7 days).

## 2026-10-16 15:05–15:50 - Phase 8 live checks, streaming live, Phase 9 code and CAI project

- Run **644** (stages land→recon, 2026-10-12..16): **succeeded** in 14 min; recon identical to
  local (only the planted bureau trailer MISMATCH on 2026-10-14).
- Run **645** producer: topics created, 1,251 backfill messages sent (run backfill-d138b32c).
- Run **646** `rsingh-mcc-stream-bronze` running; batch 0 wrote crash 222, claim_event 413,
  control 616, quarantine 0 (= all 1,251).
- DataViz: `dataviz/build_dashboard.py`, 4 dashboards / 38 visuals (PKs 14000+); every visual's
  query checked on local Spark. Not imported yet.
- Fixes found by a training/serving skew check (serving_row vs gold.claim_training_features):
  `pipeline.yaml` categoricals did not match the data (claim types, credit band NO_HIT); gold
  history features were computed over decided claims only (an open claim vanished from later
  claims' history) → now over every claim; batch scoring recomputes history point in time.
  Remaining skew: amount_vs_type_mean < 1%.
- Local chain: approval TEST AUROC 0.792, fraud TEST AUROC 0.968 / PR-AUC 0.631 (base 0.042):
  gate passed for both.
- Drift (local): psi_feature_max ALERT. The synthetic history runs at ~5.6 claims/day, the live
  dates at 40/day: volume features (garage_claims_30d) shift for real. Kept (regenerating would
  orphan the Kafka backfill); retrain trigger respects the 7-day cooldown.
- Resource re-uploaded at `7776dc0`; run **647** gold+recon for all dates (history fix).
- CAI: project `rsingh-motor-claim-copilot` (`lq1n-y700-fo51-vgx8`, blank), environment
  (Impala workload user, GROQ_*, MCC_DB_PREFIX; names only), 295 files pushed (CODE_VERSION
  7776dc0), jobs mcc-00..08 created.

## 2026-10-16 15:50–18:45 - Phase 8 and 9 live: semantic, DataViz, CAI chain, endpoint

- Run **647** gold+recon (all dates, history fix): **succeeded**.
- CDW: semantic views created; consistency checks 8/8 MATCHED for every date (2026-10-16:
  STP 31.9%, cycle time 3.66 days, loss ratio 576.5%).
- DataViz: imported on `federal-impala-1` (4 dashboards, 9 datasets, 39 visuals). `--check`
  39/39 on Impala, `--verify` 39/39 through the Data API (KPI tiles equal to Impala). The
  "Match exceptions" tile is `count(1)`: mdm.match_exception is empty, `sum(1)` showed blank.
- CAI: mcc-01 failed in 5 s. CAI serves job logs only over the UI websocket, so added
  `ci/run_logged.py` + job `mcc-99-debug` (output to outputs/logs/, fetched over the v1 files
  API). Cause: unpinned `pyarrow` resolved to 26.0.0, which needs numpy 2; the runtime image
  (python3.11 2026.08.1-b5) ships numpy 1.26.4 → pinned `pyarrow==19.0.1`.
  Also: kernel argv carries no job arguments (use job env), job `environment` is a JSON string.
- Chain at `9e94bf3`: mcc-00 → 01 → 02 → 03 (gate passed both heads) → 04 **succeeded**
  (17:57–18:02). Registry mcc-approval v1, mcc-fraud v1; endpoint `mcc-approval` built and
  deployed; a test claim returns both heads, bands, top factors and guardrails (shadow mode).
- mcc-06 (2026-10-16): 124 claims → gold.fact_model_score (avg p_approve 0.812, 4 FRAUD_REVIEW).
- mcc-05 drift: 339 claims scored, status ALERT (the volume surge above). mcc-08: RETRAIN_SKIPPED
  (cooldown 0 of 7 days, 13 of 200 new labels).
- `retrain_trigger.py --dry-run` from the laptop had published a RETRAIN_SKIPPED row for the
  laptop champion: dry run no longer publishes; that one row deleted from ref.model_event.

## 2026-10-16 18:45–22:30 - Phase 10: Copilot on CAI in shadow mode

- App code: `backend/services/approval_model_service.py` (off by default; shadow scores a claim
  after the rules decide, stores `claims.model_prediction_json`, never changes a decision),
  Model view card in Claim Insights (insurer/agent only; stripped from the customer route),
  insurer `/api/insurer/model-vs-rules` + dashboard panel (agreement with the claim's final
  decision), `backend/services/llm_guard.py` (PII redaction in the decision prompt; reasoning
  that contradicts the decision falls back to the template), `LAKEHOUSE_BRONZE_DATABASE`.
- Serving fix: a claim that names no garage (the app) had `garage_network_status=UNKNOWN`, a
  one-hot never seen in training (std 0) → OOD distance ~1e10, the model always abstained.
  Now missing garage features; UNKNOWN stays for a named garage absent from the master.
  Chain rerun at `9e82dfa` (00→04 succeeded); champion approval-1.0.0-9e82dfa-20261016154341.
- Local check against federal: the app's `ingest_lakehouse.py` reads rsingh_mcc_gold (60
  policies, 240 clauses, 837 risk signals, 800 profiles); 3 LH-POL claims scored LIKELY_APPROVE.
- CAI: project environment gains the app settings (DB_BACKEND, LAKEHOUSE_*, IMPALA_*,
  APPROVAL_MODEL_*; names only). Jobs mcc-09-app-setup, mcc-lakehouse-ingest (03:00),
  mcc-export-claims (01:45) created. setup.sh failed at the nvm Node install (no egress to
  it on federal): the SPA is built on the laptop and uploaded (`push_files.py --dist`).
  Setup run succeeded (backend venv, demo seed, ingest of mcc gold, RAG 270 vectors).
- Application `MCC Motor Claim Copilot` (an2h-0mhg-cj4x-5yg4, 2 vCPU / 8 GB), subdomain
  `rsingh-mcc-copilot`: running; /health and the SPA answer.
- End to end on CAI (a second backend in a job pod, same SQLite): claim CLMA7A06866 on
  LH-POL-2011 → rules ANALYSIS_COMPLETE, model p_approve 0.855 LIKELY_APPROVE, fraud CLEAR,
  stored. Claim CLM0E281A89 (incident 26 days before filing) → model ABSTAIN on OOD (6.64 >
  3.94): the guardrail working as intended.

## 2026-10-16 22:30–23:15 - Phase 11: governance (Atlas, Ranger)

- DataViz dashboards moved by the user to workspace "MCC - Insurance Claim Processing" (id 7);
  `dataviz/build_dashboard.py --import` now looks the workspace up by name.
- Deferred by the user to after end to end: the ~576% loss ratio (claim-dense synthetic book)
  and the drift ALERT baseline (regenerate at ~6 claims/day).
- `scripts/governance.py` + `config/governance.json`: plan (89 changes), apply, verify OK.
  Atlas: classifications MCC_SENSITIVE_HASH (names, emails, bureau_ref), _CONTACT (mobiles,
  show last 4), _DOB (show year; string dob in bronze → hash), _VEHICLE_ID (VIN, reg no, hash),
  _FINANCIAL (credit_score/band, NULL), not propagated; 82 columns tagged across bronze,
  silver, mdm, gold, semantic. Glossary "MCC Claims KPIs": STP, CCT, LR, each assigned to its
  kpi_ and mis_ view. Ranger cm_tag: rsingh-mcc-sensitive-{hash,contact,dob,vehicle-id,
  financial}, masking federal01 only; rsingh and federal07 clear.
- Checked as rsingh: mobile, credit_score, dob, vin clear (training and app reads unaffected).
  The federal01 masked view is not checked here (no federal01 credentials in .env).
