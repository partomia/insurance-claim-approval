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
