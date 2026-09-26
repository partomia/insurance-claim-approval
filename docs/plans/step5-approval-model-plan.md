# Step 5 Plan — Trained Approval Model (CDE features → CAI Model endpoint, shadow mode)

**Status:** not started (planned 2026-09-26). Steps 1-4 (Customer Trust Score)
are done and verified live in env 1 — see `MEMORY_DUMP.md` (2026-09-23 and
2026-09-25 entries) and `cml/README.md` § Customer Trust Score.
**Target env:** env 1 only (CDP 7.3.2 with CDE + CAI). env 2 (standalone,
OLTP-only) must behave exactly as today — every piece below is off by default.
**Branch:** do this on `feature/approval-model`, merge to `main` only after
the env 1 check — env 2 and the CDE Repository both track `main`.

---

## 1. Goal

Today every decision is hand-written rules: the Customer Trust Score weights,
the fraud signal weights and the decision thresholds were all set by hand.
Step 5 adds a **learned model** that predicts, for a new claim:

- `p_approve` — probability the claim ends up approved, and
- `p_fraud_review` — probability it needs a fraud review,

with the **top contributing factors** for each prediction, served from a
**CAI Model endpoint** and shown next to the rules' decision.

It starts in **shadow mode**: the model's prediction is displayed and logged
but never changes an outcome. Only after comparing model vs rules on real
claims do we decide whether (and how) to let it influence anything.

## 2. Non-goals / guardrails

- The model never causes `REJECTED` and never blocks a payout on its own —
  same principle as the trust tier. Any future "active" use is limited to
  routing (auto-approve vs human review), never denial.
- No protected attributes as features (no age, gender, location-as-proxy).
  `driver_age` stays excluded, same as the trust score.
- Nothing customer-visible: model output is insurer/expert-only, like the
  trust card and lakehouse risk card (`InsightsPanel showInsurerAnalytics`,
  customer insights/audit APIs stripped in `routers/claims.py`).
- If the endpoint is unset, slow or down, the app decides exactly as today.

## 3. Current data — and the one blocker

| Source | What it has | Join key |
|--------|-------------|----------|
| `insurance_lakehouse_bronze.claims_history_raw` → `insurance_lakehouse_silver.claims_history` (`generate_claims_bronze.py`, `transform_claims_silver.py`; silver also unions `app_claims_raw`) | ~4,000 synthetic claims over 800 policies: claim_type, amount_requested/approved, status, garage, dates | `policy_number` (`LH-POL-2000..2799`) |
| `insurance_lakehouse.policy_risk_signals` | per-policy fraud_risk_score, band, claim counts, high-risk garage link | `policy_number` |
| `insurance_lakehouse.garage_risk_signals` | per-garage payout anomaly / flag | `garage_name` |
| `insurance_lakehouse.customer_profile_signals` | 800 customers: credit, defaults, driving record, tenure, other-insurer claims | `customer{i}@example.com` ↔ `LH-POL-{2000+i}` |
| `insurance_lakehouse_bronze.app_claims_raw` (via `export-claims`) | real claims filed through the app, with the app's decision | `policy_number` |

**Blocker:** in `generate_claims_bronze.py` the claim `status` is drawn with
fixed weights (`STATUS_WEIGHTS = [0.60, 0.15, 0.15, 0.10]`) *independently of
every feature*. A model trained on that learns nothing (AUC ≈ 0.5). Phase 0
fixes this.

## 4. Phases

### Phase 0 — Make synthetic outcomes learnable (CDE)
- In `generate_claims_bronze.py`, draw `status` from a logistic function of
  latent risk instead of fixed weights. Inputs: high-risk garage, amount
  outlier vs claim-type mean, frequent-claimant policy, and the customer's
  latent "care" from `generate_customer_profile_bronze.py` (regenerate it
  deterministically from the same seed/customer index, or read the silver
  customer table). Add noise so it's not perfectly separable.
- Keep the overall mix close to today's (~60/15/15/10) so existing
  dashboards, `policy_risk_signals` bands and demo runbook numbers don't
  shift noticeably. Keep calendar-day seeding + `seed|YYYY-MM-DD` override.
- Add a `fraud_confirmed` boolean (small %, concentrated in high-risk
  garages + outlier amounts) as the second label.
- **Done when:** a quick local logistic regression on the generated rows
  reaches AUC ≳ 0.75 for approve and the status mix is within ±3 pts.

### Phase 1 — Training table (CDE gold)
- New job `cde/jobs/curate/curate_claim_features_gold.py` →
  `insurance_lakehouse.claim_training_features`, one row per historical claim
  with **point-in-time** features (only information available at filing
  time — no future claims leaking into counts):
  - claim: type, amount, amount vs type mean, days incident→filed
  - policy: coverage, amount/coverage ratio, prior claims (12m / total, as of
    filing), deductible, co-pay
  - garage: high-risk flag, payout anomaly score
  - customer: credit score/band, defaults, driving band, violations, tenure,
    policies held, other-insurer claims, address change
  - labels: `label_approved` (APPROVED vs REJECTED; PENDING/UNDER_REVIEW
    excluded), `label_fraud_review`
  - `source` (`SYNTHETIC` / `APP`), `split` (time-based train/test)
- Same `_bootstrap_or_merge` pattern as other gold jobs; add to
  `deploy_jobs.sh`, the DAG (after claims + customer chains) and
  `time_travel_drill.sh`; add to `GOLD_TABLES` in `lakehouse_time_travel.py`.
- **Done when:** table populated in env 1, row count ≈ approved+rejected
  claims, no nulls in required features.

### Phase 2 — Training (CAI Job)
- New `cml/jobs/train_approval_model.py` (pattern: existing
  `cml/jobs/lakehouse_ingest_job.py`) + `bash cml/cli.sh model train`.
- Read `claim_training_features` via Impala (reuse `ingest_lakehouse.py`
  connection helpers). Train two gradient-boosted classifiers
  (scikit-learn `HistGradientBoostingClassifier`, or XGBoost if already in
  deps — prefer no new heavy deps). Time-based split.
- Explainability: per-prediction top factors via SHAP if lightweight enough,
  else permutation importance + signed contribution approximation.
- Save to `models/approval/<version>/` in the project: model file,
  `feature_list.json`, `metrics.json` (AUC, precision/recall at the review
  threshold, calibration), `model_card.md` (data, features, exclusions,
  intended use = shadow).
- **Done when:** metrics.json shows AUC ≳ 0.75 on the time-based test split
  and a model card exists. Schedule as a CAI Job (weekly) after first run.

### Phase 3 — Serving (CAI Model endpoint)
- New `cml/models/approval_model.py` with a `predict(args)` function (CAI
  Model convention): input = feature dict, output =
  `{model_version, p_approve, p_fraud_review, top_factors: [{feature, label,
  impact}], }`. Human-readable factor labels, reusing trust-service wording
  where it overlaps.
- Deploy via CAI UI or API; document the steps + access key handling in
  `cml/README.md`. Smoke: `bash cml/cli.sh model predict --policy-number …`.
- **Done when:** endpoint returns a prediction for a sample payload in < 1 s.

### Phase 4 — App integration (shadow mode)
- Config (all off by default, commented in `.env.example`, rows in
  `docs/env-reference.md`): `APPROVAL_MODEL_URL`, `APPROVAL_MODEL_ACCESS_KEY`,
  `APPROVAL_MODEL_MODE=off|shadow` (later maybe `route`),
  `APPROVAL_MODEL_TIMEOUT_S=2`.
- New `backend/services/approval_model_service.py`: builds the **same
  feature vector as training** from the app DB (Claim, Policy,
  PolicyRiskSignal, CustomerProfileSignal, garage if known) — share the
  feature definitions in one module to avoid train/serve skew. Calls the
  endpoint with timeout; any error → `None`.
- In `finalize_claim` (`services/claim_pipeline.py`): after the rules
  decision, if mode=shadow, call the model and store the result on a new
  nullable column `claims.model_prediction_json` (additive — `ensure_schema`
  heals it). Log `MODEL_SHADOW_PREDICTION` to the audit log. Decision is
  untouched. Strip the key from customer audit payloads like
  `customer_trust`.
- Store agreement: `model_agrees = (p_approve ≥ 0.5) == (status == ANALYSIS_COMPLETE)`.
- **Done when:** with mode=off, all current tests + `/tmp`-style integration
  checks pass unchanged; with mode=shadow and a stub endpoint, predictions
  are stored and decisions identical.

### Phase 5 — UI + comparison
- Claim Insights (insurer/expert only): "Model view" card — p_approve,
  p_fraud_review, top factors, agrees/disagrees with the rules decision,
  model version.
- Insurer dashboard or Book of Business: small "Model vs rules" panel —
  agreement rate, list of disagreements to review.
- `test-claim submit` prints the model line when present.
- Demo runbook: a "Beat 2c — the model's second opinion" section.
- **Done when:** a disagreement case can be shown end-to-end in env 1.

### Phase 6 (later, only after review) — Route mode
- Possible active use: model confidence can *send* a rules-auto-approved
  claim to human review (never the reverse, never reject). Needs agreement
  data from shadow mode first + explicit sign-off.

## 5. Suggested order of work (sessions)

1. Phase 0 + local check (no env access needed).
2. Phase 1 locally with Spark + Iceberg (the `/tmp` setup used for the trust
   jobs), then deploy + run in env 1.
3. Phase 2 training locally on an exported sample, then as a CAI Job.
4. Phase 4 with a stub endpoint (fully local), then Phase 3 endpoint in env 1.
5. Phase 5 UI, env 1 end-to-end, merge to `main`.

## 6. Risks and open questions

- **Synthetic-data circularity:** the model can only learn what Phase 0's
  generator encodes. Be upfront in the demo — the value shown is the
  *pipeline* (features → train → serve → shadow compare), not real-world
  accuracy. `app_claims_raw` adds real app outcomes over time but is small.
- **Train/serve skew:** features must be computed identically in Spark and
  in the app — keep one definition list and test it.
- **Point-in-time leakage:** prior-claim counts must exclude claims after the
  filing date.
- **Endpoint auth/latency in CAI:** confirm Model access-key handling and
  that an Application pod can reach the Model endpoint.
- **Open:** SHAP vs simpler attribution (dependency weight on CAI runtime)?
- **Open:** which labels matter most for the demo — approve, fraud, or both?
- **Open:** retrain cadence (weekly Job?) and model version pinning in the app.

## 7. How to resume

1. Read this file + the latest `MEMORY_DUMP.md` entries.
2. `git checkout -b feature/approval-model` from `main`.
3. Start Phase 0 in `cde/jobs/generate/generate_claims_bronze.py`.
