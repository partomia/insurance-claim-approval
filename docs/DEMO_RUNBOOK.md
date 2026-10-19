# Demo runbook: Motor Claim Copilot on Cloudera (about 30 minutes)

Before the session: `scripts/platform_ctl.py status`, then `start` if anything is stopped (see
"Start and stop" below). After it: `stop`.

Links:

- Copilot app (CAI): https://rsingh-mcc-copilot.federal-cml.federal.dp5i-5vkq.cloudera.site
  (CAI project `rsingh-motor-claim-copilot` → Applications → "MCC Motor Claim Copilot"; CAI SSO first).
- Dashboards (CDW Data Visualization): https://viz-indianbank-spend-analytics.dw-federal-cdp-env.dp5i-5vkq.cloudera.site/arc/apps/
  → workspace **MCC - Insurance Claim Processing** → **MCC Claims KPIs**, **MCC Claims & Fraud Signals**,
  **MCC Reconciliation & Data Quality**, **MCC Customer Master**
- CDE (virtual cluster `federal-cde-vc`): jobs `rsingh-mcc-*`; streaming run `rsingh-mcc-stream-bronze`
- Hue / Impala (`federal-impala-1`): databases `rsingh_mcc_bronze`, `_silver`, `_mdm`, `_gold`, `_semantic`, `_ref`
- Kafka (`federal-kafka`): topics `mcc.claim.events`, `mcc.telematics.crash`, `mcc.control`
- CAI project `rsingh-motor-claim-copilot`: Jobs `mcc-00`..`mcc-08`, Experiments, Model Registry
  `mcc-approval` / `mcc-fraud`, Model `mcc-approval`
- Atlas / Ranger: classifications `MCC_SENSITIVE_*`, glossary **MCC Claims KPIs**, policies `rsingh-mcc-sensitive-*`

Demo logins (seed data, `backend/scripts/seed.py`; OTP is `112233` where asked):

| Role | Page | User | Password |
|------|------|------|----------|
| Customer | `/auth` | `test@example.com` (or `customer7@example.com`, a lakehouse policy holder) | `password123` |
| Expert / agent | `/agent/auth` | `expert1@claimcopilot.in`, `expert2@claimcopilot.in` | `password123` |
| Insurer | `/insurer/auth` | `insurer1@claimcopilot.in` | `password123` |

## 1. The problem (2 min)

A motor insurer receives a claim at first notice of loss (FNOL) from the portal, the call centre
or a telematics crash alert. The data it needs sits in separate systems that name the same
customer and vehicle differently: the policy admin system, the claims system, a credit bureau, the
garage network and telematics. Today an adjuster pieces it together by hand, so cycle time is
long and fraud signals are seen late.

## 2. One customer, one vehicle (4 min): DataViz → MCC Customer Master

- Show the cross-reference: bureau, policy and claim records resolved to one golden customer, with
  the rule and score of each match (`rsingh_mcc_mdm.customer_golden`, `customer_xref`).
- Match exceptions: records the MDM rules would not auto-merge, left for a data steward.
- VIN cross-reference (`vehicle_xref`): the policy VIN versus the crash-alert VIN.

## 3. File a claim (6 min): Copilot app, customer then insurer

- As `customer7@example.com`, file a motor claim on policy LH-POL-2007 or LH-POL-2011 with the
  documents in `docs/demo-assets/`.
- The pipeline runs the rules decision; the approval model scores the claim **in shadow**: it
  never changes the decision.
- As `insurer1`, open the claim → Claim Insights: the **Model view** card (p_approve, band, fraud
  band, top factors, guardrail result) next to the rules decision. Customers never see it.
- Insurer dashboard → **Model vs rules**: agreement between the model and final decisions.

## 4. Streaming (4 min): CDE + Kafka

- `rsingh-mcc-stream-bronze` reads the three topics into `bronze.stream_*` (checkpointed, no gap
  and no duplicate after a restart).
- On the scheduled dates the DAG `mcc_live_stream` runs the stream and the live producer from
  09:00 to 19:00 IST (03:30-13:30 UTC); both stop themselves, and the nightly batch (02:00 IST)
  waits for them before replaying the day. A demo inside that window needs nothing.
- Outside it: `./cde/scripts/mcc_deploy_streaming.sh live 30` (stream + producer for 30 min; it
  never runs into the batch and refuses while the batch runs).
- Crash alerts are matched to claims (`silver.crash_event` → `crash_event_match`), visible on
  **MCC Claims & Fraud Signals**.

## 5. Trust: reconciliation and KPI consistency (5 min): DataViz → MCC Reconciliation & Data Quality

- Each load is audited (`ref.load_audit`: rows in, out, rejected) and reconciled against the
  source trailer (`ref.recon_results`); rejected rows go to quarantine with their reasons.
- Certified KPIs: straight-through rate, claim cycle time, loss ratio. Each is defined once
  (`config/kpi.json`, `sql/semantic/1*_kpi_*.sql`); the dashboards and the app read the same views.

## 6. Models, guardrails and MLOps (5 min): CAI project

- Chain `mcc-00` → `mcc-04`: features, train and validate (approval and fraud heads), KPI gate,
  deploy the champion to `mcc-approval`. Registry versions and MLflow runs in Experiments.
- Guardrails: input checks (policy and customer resolved, required features), an
  out-of-distribution check that makes the model **ABSTAIN** (for example, an incident reported
  26 days late), and output bands. In the app, PII is redacted from the LLM prompt, and reasoning
  that contradicts the decision falls back to the template (`backend/services/llm_guard.py`).
- Nightly: `mcc-06` batch scoring into `gold.fact_model_score`, `mcc-05` drift, `mcc-08` retrain trigger.

## 7. Governance (2 min): Atlas and Ranger

- Atlas: `MCC_SENSITIVE_*` classifications on names, emails, mobiles, dates of birth, VINs,
  registration numbers and credit scores across every `rsingh_mcc_*` layer; glossary **MCC
  Claims KPIs** assigned to the certified and MIS views.
- Ranger tag masking `rsingh-mcc-sensitive-*`: `federal01` sees hashes, the last 4 digits of a
  mobile, the year of birth and a NULL credit score; `rsingh` and `federal07` see clear values.
  Show it in Hue: `SELECT full_name, mobile, dob, credit_score FROM rsingh_mcc_gold.dim_customer LIMIT 5`
  as each user.

## 8. Close (2 min)

Everything is code in a private repo (no secrets; gitleaks hook), one commit per phase, and every
live run is in `docs/PROJECT_LOG.md`.

## Start and stop

```bash
set -a; source .env; set +a
.venv/bin/python scripts/platform_ctl.py status            # always first
.venv/bin/python scripts/platform_ctl.py stop --dry-run    # the plan
.venv/bin/python scripts/platform_ctl.py stop              # or start
.venv/bin/python scripts/platform_ctl.py status            # always last
```

The default scope is this project only: the CAI app, model `mcc-approval`, CAI schedules
(`mcc-export-claims`, `mcc-05`, `mcc-08`, `mcc-lakehouse-ingest`; stop clears the cron and start
sets it back), and CDE `rsingh-mcc-*` runs (the live stream included) and the two DAG schedules.
Data, topics and checkpoints are kept. `start` does not start the stream: its DAG does, inside the
live window. `--scope platform --yes-shared` also stops Kafka, CDW, the CDE virtual
cluster and the CAI workspace, which sibling demos share: ask first, every time.

## If something is off

- The app shows a CAI "Application stopped" page: `platform_ctl.py start --only cai` (about 30 s
  for the app, 1 to 3 min for the model endpoint).
- The Model view card says "Model not available for this claim": the endpoint is down or restarting.
  The rules decision is unaffected; restart with `start --only cai` and file a new claim.
- The Model view says ABSTAIN: the guardrail is working (out-of-distribution or a missing
  feature); the reason is on the card.
- A dashboard is empty for the latest date: the CDE chain for that date has not finished; pick
  the previous date.
- Known and deferred: the loss ratio is about 576% (the synthetic book is claim-dense), and
  `mcc-05` reports drift ALERT until the reference is regenerated at about 6 claims a day.
