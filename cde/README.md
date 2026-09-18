# Insurance Lakehouse Medallion Pipeline (CDE)

Phase 2 of the datalakehouse story: a real bronze → silver → gold Spark
pipeline on Cloudera Data Engineering (CDE), orchestrated with Airflow,
replacing Phase 1's hand-seeded Iceberg tables (`cml/cli.sh lakehouse seed`)
with a proper pipeline. Orchestration pattern (jobs + `CDEJobRunOperator`
Airflow DAG) follows
[`Cloudera-CDE-Workshop-with-Orchestration-and-CI-CD`](https://github.com/partomia/Cloudera-CDE-Workshop-with-Orchestration-and-CI-CD),
but job/DAG **source files come from a CDE Repository** (Git integration,
GA since CDE 1.24.1 / June 2025) pointed at this GitHub repo, instead of
manually uploading each script as a `files` Resource — push to `main`,
`cde repository sync`, and every Spark job picks up the new code with no
re-upload step.

Extended with **Phase 2b: claims-analytics medallion pipeline** — a second
bronze→silver→gold chain over a much larger synthetic *claims history*
population (~800 policies, ~4,000 claims) that computes real datalakehouse-
style analytics (fraud risk scores, peer benchmarks, garage anomaly
detection) that a single OLTP query could never produce. It runs after
`curate-gold` in the same DAG, publishing two new gold tables:
`policy_risk_signals` and `garage_risk_signals`.

**Status: fully deployed and validated end-to-end** — both individually
(all 8 jobs) and via the full Airflow-orchestrated DAG (all 8 tasks chained)
— on vcluster `cluster-pjq5xtvb`. See [Live deployment](#live-deployment-reference)
below for the exact resource names, and [Gotchas we actually hit](#gotchas-we-actually-hit)
for real bugs found while validating and how they were fixed. Note: this
vcluster was deleted and recreated once (disabling the CDE service deleted
it entirely, including all jobs/repositories) — everything below was
re-deployed from scratch via the same `deploy_jobs.sh` / `deploy_dag.sh`
scripts with zero code changes, confirming the whole setup is reproducible
from Git alone.

```
cde/
├── jobs/
│   ├── generate/
│   │   ├── generate_bronze.py             ← Stage 1: synthesize raw policy data -> bronze
│   │   └── generate_claims_bronze.py      ← Stage 1b: synthesize ~4,000 claims -> bronze
│   ├── validate/
│   │   ├── validate_bronze.py             ← Stage 2: policy data-quality gate
│   │   └── validate_claims_bronze.py      ← Stage 2b: claims data-quality gate
│   ├── transform/
│   │   ├── transform_silver.py            ← Stage 3: clean/dedupe/type-cast -> silver
│   │   └── transform_claims_silver.py     ← Stage 3b: clean/dedupe claims -> silver
│   └── curate/
│       ├── curate_gold.py                 ← Stage 4: enrich + finalize -> gold (app-facing tables)
│       └── curate_risk_signals_gold.py    ← Stage 4b: fraud/risk analytics -> gold
├── dags/
│   └── insurance_lakehouse_dag.py     ← Airflow DAG chaining all 8 jobs via CDEJobRunOperator
├── resources/
│   └── requirements.txt               ← CDE python-env deps (empty today — see below)
└── scripts/
    ├── deploy_jobs.sh                 ← Create/sync the CDE Repository + create the 8 Spark jobs
    └── deploy_dag.sh                  ← Register/update the Airflow DAG job
```

## Prerequisites

1. **CDE CLI installed and configured**, pointed at your vcluster:
   ```bash
   cat ~/.cde/config.yaml
   # cdp-endpoint: https://console.<region>.cdp.cloudera.com
   # vcluster-endpoint: https://<host>/dex/api/v1
   # credentials-file: ~/.cde/credentials
   ```
   Sanity-check connectivity before doing anything else:
   ```bash
   cde resource list
   ```
   If this fails, see [Connectivity troubleshooting](#connectivity-troubleshooting) below.
2. This repo pushed to GitHub (or another Git host reachable from your CDE
   environment) — CDE pulls job/DAG source directly from there via a
   Repository, it does not need a local clone.
3. An Airflow-enabled CDE virtual cluster (required for `deploy_dag.sh`; the
   8 Spark jobs from `deploy_jobs.sh` work on any vcluster).

## One-time setup (from scratch)

If you're deploying this fresh (not reusing the names below), edit the
`REPO_NAME` / `PYTHON_ENV` / job-name variables at the top of
`deploy_jobs.sh` and `deploy_dag.sh` first — pick a prefix that won't
collide with other users on a shared vcluster (this deployment uses an
`rsingh-` prefix for exactly that reason).

```bash
./cde/scripts/deploy_jobs.sh   # creates/syncs the Repository, the python-env, and the 8 Spark jobs
./cde/scripts/deploy_dag.sh    # registers the Airflow DAG job (sourced from the same Repository)
```

`deploy_jobs.sh`:
1. Creates a CDE **Repository** (`cde repository create --type` is implicit;
   `--url`/`--branch` point at this GitHub repo) if it doesn't already exist,
   then `cde repository sync`s it to the latest commit on `main`.
2. Creates/uploads a **python-env** Resource from `cde/resources/requirements.txt`
   (empty today — all 8 jobs use only PySpark). **This resource takes 1–3
   minutes to build** (CDE builds a container image from it) — running a job
   before it's `ready` fails with `cannot use resource '...' in status
   'building'`. Poll with:
   ```bash
   cde resource describe --name rsingh-insurance-lakehouse-python-env
   ```
3. Creates the 8 Spark jobs (4 policy-pipeline + 4 claims-analytics-pipeline),
   each with `--mount-1-resource <repo>` and `--application-file <repo-relative-path>`
   (e.g. `cde/jobs/generate/generate_bronze.py`) — a Repository mount preserves
   the full directory structure, unlike a flat `files` Resource.

`deploy_dag.sh` registers `cde/dags/insurance_lakehouse_dag.py` as a proper
`--type airflow` job (see [Gotcha #1](#gotchas-we-actually-hit) for why it
must be `airflow`, not `spark`).

**Private repo?** Pass a GitHub Personal Access Token (`repo:read` scope) —
only needed the first time the Repository is created:
```bash
GIT_CREDENTIAL=ghp_xxx ./cde/scripts/deploy_jobs.sh
```

## Day-2 workflow (after any code change)

```bash
git push origin main
cde repository sync --name rsingh-insurance-claim-cai-pipeline
```
This is enough for the 4 **Spark** jobs — they read the file fresh from the
mounted Repository on every run.

**If you changed `cde/dags/insurance_lakehouse_dag.py` specifically**, the
sync above is *not* enough — you must also re-register the DAG (see
[Gotcha #2](#gotchas-we-actually-hit)):
```bash
./cde/scripts/deploy_dag.sh
```

## Run

**Whole pipeline, via Airflow** (proves out the real `CDEJobRunOperator` chaining):
```bash
cde job run --name rsingh-insurance-claim-cai-pipeline-orchestration
# poll:
cde run list --filter "id[eq]<run-id>"
```
Or via the CDE Airflow UI → DAGs → `insurance_lakehouse_pipeline` → trigger.
It's `schedule_interval=None` by default (manual trigger) — flip to
`"@daily"` etc. in `dags/insurance_lakehouse_dag.py` once you're happy with it.
Takes ~20–30 min end-to-end (8 sequential Spark job cold-starts + Airflow overhead).

**One stage at a time, via CDE CLI** (faster feedback while iterating):
```bash
# Policy pipeline
cde job run --name rsingh-insurance-generate-bronze  --wait
cde job run --name rsingh-insurance-validate-bronze  --wait
cde job run --name rsingh-insurance-transform-silver --wait
cde job run --name rsingh-insurance-curate-gold      --wait

# Claims-analytics pipeline (depends on nothing above except the schemas existing)
cde job run --name rsingh-insurance-generate-claims-bronze   --wait
cde job run --name rsingh-insurance-validate-claims-bronze   --wait
cde job run --name rsingh-insurance-transform-claims-silver  --wait
cde job run --name rsingh-insurance-curate-risk-signals-gold --wait
```

**Check logs for a run:**
```bash
cde run list --filter "job[eq]rsingh-insurance-generate-bronze"   # get the run id
cde run logs --id <run-id> --show-types                            # see available log streams
cde run logs --id <run-id> --type driver/stdout                    # Spark job logs
cde run logs --id <run-id> --type <task_id>/attempt_1              # Airflow task logs (DAG runs)
```

## Verify the result

Same commands as Phase 1, now backed by pipeline-produced data (`source = 'GOLD_PIPELINE'`, ~60 rows, instead of Phase 1's 3 `SEED` rows):
```bash
bash cml/cli.sh lakehouse verify   # run from inside the CAI session (needs backend/.env)
```
or in Hue (Impala SQL editor):
```sql
INVALIDATE METADATA;  -- Hue's Impala catalog cache is often stale after a pipeline run
SELECT COUNT(*), source FROM insurance_lakehouse.policy_master GROUP BY source;
SELECT risk_band, COUNT(*), ROUND(AVG(premium_to_coverage_pct), 2) AS avg_ratio
FROM insurance_lakehouse.policy_master
GROUP BY risk_band;
```

**Claims-analytics gold tables** (new in Phase 2b):
```sql
INVALIDATE METADATA;
SELECT claim_risk_band, COUNT(*) FROM insurance_lakehouse.policy_risk_signals GROUP BY claim_risk_band;
SELECT policy_number, total_claims_count, fraud_risk_score, claim_risk_band, linked_high_risk_garage
FROM insurance_lakehouse.policy_risk_signals
ORDER BY fraud_risk_score DESC
LIMIT 20;
SELECT garage_name, claim_count, avg_payout, payout_anomaly_score, flagged_high_risk
FROM insurance_lakehouse.garage_risk_signals
WHERE flagged_high_risk = true
ORDER BY payout_anomaly_score DESC;
```
Last validated run: 792 `policy_risk_signals` rows (HIGH=76, MEDIUM=439, LOW=277) and 40 `garage_risk_signals` rows (6 flagged high-risk).

## Live deployment reference

Actual resource names on vcluster `cluster-pjq5xtvb` (rename via the
variables at the top of each script if you deploy under a different prefix):

| Resource | Name | Type |
|---|---|---|
| Repository | `rsingh-insurance-claim-cai-pipeline` | git, → `https://github.com/partomia/insurance-claim-approval` @ `main` |
| Python env | `rsingh-insurance-lakehouse-python-env` | python-env |
| Job (bronze) | `rsingh-insurance-generate-bronze` | spark |
| Job (validate) | `rsingh-insurance-validate-bronze` | spark |
| Job (silver) | `rsingh-insurance-transform-silver` | spark |
| Job (gold) | `rsingh-insurance-curate-gold` | spark |
| Job (claims bronze) | `rsingh-insurance-generate-claims-bronze` | spark |
| Job (claims validate) | `rsingh-insurance-validate-claims-bronze` | spark |
| Job (claims silver) | `rsingh-insurance-transform-claims-silver` | spark |
| Job (risk signals gold) | `rsingh-insurance-curate-risk-signals-gold` | spark |
| Job (orchestration) | `rsingh-insurance-claim-cai-pipeline-orchestration` | **airflow**, DAG ID `insurance_lakehouse_pipeline` |

## Gotchas we actually hit

1. **Airflow job created as `type: spark` instead of `type: airflow`.**
   Symptom: `spark-submit`-ing the DAG file directly fails immediately with
   `ModuleNotFoundError: No module named 'airflow'` — and even if it didn't,
   running a DAG *file* as a script doesn't register/schedule anything in
   Airflow. Fix: the orchestration job must be created with
   `--type airflow --dag-file <path> --mount-1-resource <repo>` (this is
   what `deploy_dag.sh` does; it also auto-detects and repairs a
   wrong-typed existing job by deleting + recreating it).

2. **`cde repository sync` does not refresh an already-registered Airflow
   DAG.** After fixing a bug in `insurance_lakehouse_dag.py` and running
   `git push` + `cde repository sync`, the very next DAG run still failed
   with the *old*, pre-fix error — because CDE's Airflow only picks up a new
   DAG version when the job is explicitly updated. Fix: after any change to
   a DAG file, run `./cde/scripts/deploy_dag.sh` (which does both the sync
   *and* `cde job update --dag-file ...`), not just `cde repository sync`.
   Give it ~30s after the update for Airflow's DAG file processor to
   re-parse before triggering.

3. **`CDEJobRunOperator` `job_name` values in the DAG must exactly match**
   the deployed CDE job names, including any shared-vcluster prefix (e.g.
   `rsingh-insurance-generate-bronze`, not `insurance-generate-bronze`).
   A mismatch fails every task immediately with
   `404:Not Found:{"status":"error","message":"could not get job from storage: job not found"}`.
   If you rename jobs in `deploy_jobs.sh`, update `dags/insurance_lakehouse_dag.py`
   in the same commit.

4. **python-env resource takes time to build.** `cde job run` on a job
   attached to a still-`building` python-env resource fails fast with
   `cannot use resource '...' in status 'building'`. Poll
   `cde resource describe --name <python-env>` for `"status": "ready"`
   before running jobs right after `deploy_jobs.sh`.

5. **Disabling a CDE Service deletes it entirely, not just pauses it** —
   including every vcluster, Repository, Resource, and Job underneath it.
   There is no "disable and re-enable later" for a CDE Service. Recovery is
   just re-provisioning a new Service/vcluster, pointing `~/.cde/config.yaml`
   at the new `vcluster-endpoint`, and re-running `deploy_jobs.sh` +
   `deploy_dag.sh` — since everything here is defined in Git, this is a
   ~15-minute full recovery with zero code changes (confirmed live: this
   exact pipeline was rebuilt from scratch this way and re-validated
   end-to-end). Lesson: only disable a CDE Service if you genuinely intend
   to delete it.

## Connectivity troubleshooting

If `cde resource list` (or any `cde` command) hangs or errors:
- Add `-v` for verbose HTTP/auth logs.
- Check for a DNS resolution failure on your vcluster's gateway hostname
  (`dial tcp: lookup ... no such host`) — this usually means you're not on
  the VPN/network required to reach that CDP environment. Confirm with
  `nslookup <vcluster-endpoint-host>`.
- Confirm the control-plane view of the vcluster matches your local config:
  `cdp de list-vcs --cluster-id <service-id>` (get `<service-id>` from
  `cdp de list-services`) — compare its `jobsApiUrl` to `vcluster-endpoint`
  in `~/.cde/config.yaml`.

## Python environment

`deploy_jobs.sh` creates a separate CDE `python-env` Resource
(`rsingh-insurance-lakehouse-python-env`) from `cde/resources/requirements.txt`
and attaches it to all 4 jobs via `--python-env-resource-name` — this stays
a regular uploaded Resource since a Repository can't build a Python
environment. It's intentionally empty right now — all 4 jobs use only
PySpark, which the CDE Spark runtime already provides — but it's wired up
so adding a real dependency later (Faker for richer synthetic data, Great
Expectations for the validate stage, etc.) is just editing that one file
and re-running `deploy_jobs.sh`, no job redefinition needed.

## Data flow

| Stage | Reads | Writes | Purpose |
|---|---|---|---|
| **generate** | — (synthesizes data) | `insurance_lakehouse_bronze.policy_master_raw`, `.policy_clauses_raw` | Stand-in for a real source extract; ~60 synthetic motor policies + clause text |
| **validate** | bronze | — (pass/fail only) | Null/duplicate/referential-integrity checks; `sys.exit(1)` fails the DAG run if violated |
| **transform** | bronze | `insurance_lakehouse_silver.policy_master`, `.policy_clauses` | Trim/standardize strings, cast types, dedupe by `policy_number` |
| **curate** | silver | `insurance_lakehouse.policy_master`, `.policy_clauses` | Adds `risk_band` + `premium_to_coverage_pct`; writes to the **same gold tables Phase 1 created** |
| **generate (claims)** | — (synthesizes data) | `insurance_lakehouse_bronze.claims_history_raw` | ~4,000 synthetic claims over an ~800-policy historical universe, with seeded outliers (frequent claimants, inflated amounts, high-risk garages) |
| **validate (claims)** | claims bronze (+ informational read of `policy_master_raw`) | — (pass/fail only) | Null/duplicate/amount/date/enum checks; policy-number overlap with `policy_master` logged as informational, not a hard failure |
| **transform (claims)** | claims bronze | `insurance_lakehouse_silver.claims_history` | Trim/standardize strings, dedupe by `claim_id` |
| **curate (risk signals)** | claims silver | `insurance_lakehouse.policy_risk_signals`, `.garage_risk_signals` | Computes `fraud_risk_score`/`claim_risk_band` per policy and payout-anomaly flags per garage — see below |

The gold tables are the exact ones `cml/cli.sh lakehouse verify` already checks and Hue already queries — running this pipeline just replaces the hand-seeded 3 rows with ~60 pipeline-produced rows, no downstream changes needed.

All tables are `STORED AS ICEBERG` (`format-version=2`), written via `CREATE TABLE ... USING iceberg AS SELECT` (full drop+recreate each run — simplest for a demo pipeline; a production version would use `MERGE`/`INSERT OVERWRITE` to preserve Iceberg snapshot history instead).

## Claims-analytics design (Phase 2b)

`curate_risk_signals_gold.py` is the actual "datalakehouse speciality"
payoff of this pipeline — analytics over the *entire* claims-history
population that a single OLTP row/query could never produce:

- **Why a separate, bigger dataset than `policy_master`?** Percentiles and
  peer-group benchmarks are only meaningful over a large population.
  `policy_master` has ~60 "currently active" rows; `claims_history` covers
  an ~800-policy historical universe (a realistic claims warehouse holds
  history for lapsed/renewed policies too, not just the current book) with
  ~4,000 claims — `policy_risk_signals` therefore covers more policies than
  `policy_master`, and that's by design (see `validate_claims_bronze.py`'s
  informational-only overlap check).
- **`fraud_risk_score` (0–100) per policy** — a weighted composite of:
  - 50% claim-frequency percentile rank (`percent_rank()` window function
    over trailing-12-month claim counts, across the full population),
  - 30% how far this policy's average claim amount deviates from its
    claim-type peer average (segment benchmark via a `Window.partitionBy("claim_type")`),
  - 20% whether any of its claims were filed at a garage flagged high-risk.
  Bucketed into `claim_risk_band` (`LOW` ≤ 33, `MEDIUM` ≤ 66, `HIGH` > 66).
- **`garage_risk_signals`** — per-garage claim volume + average payout, with
  a z-score-based `payout_anomaly_score` (payout vs. population mean/stddev)
  and `flagged_high_risk` if the z-score exceeds 1.5 *or* claim volume
  exceeds 2.5x the average garage's volume.
- Seeded outliers to make the analytics non-trivial: ~8% of policies are
  "frequent claimants" (4–8 claims), ~5% of claims have inflated amounts
  (2.5–4x their claim-type peer average), and 3 of 40 garages are
  deliberately overrepresented ("high-risk").
- **Does not sync back to the app's SQLite OLTP DB yet** — that's a
  separate, later step (see Roadmap) once this analytics layer is
  validated on its own.
- Last validated run: 792 `policy_risk_signals` rows (`HIGH`=76,
  `MEDIUM`=439, `LOW`=277) and 40 `garage_risk_signals` rows (6 flagged
  high-risk) — a healthy, non-degenerate spread, not everything dumped into
  one bucket.

## Config knobs

- `INSURANCE_N_POLICIES` (Airflow Variable, default `60`) — how many synthetic policies `generate_bronze.py` creates. Set via CDE Airflow UI → Admin → Variables, or `airflow variables set INSURANCE_N_POLICIES 200`.
- `INSURANCE_N_CLAIMS` (Airflow Variable, default `4000`) — how many synthetic claims `generate_claims_bronze.py` creates. `airflow variables set INSURANCE_N_CLAIMS 6000`.

## Roadmap

- ~~**Phase 3** — an app-side ingestion script pulling `insurance_lakehouse.policy_master`/`policy_clauses`/`policy_risk_signals` into the app's SQLite + Chroma RAG index~~ — **done**, see `backend/scripts/ingest_lakehouse.py` / `bash cml/cli.sh lakehouse ingest` (documented in `cml/README.md`).
- Swap `generate_bronze.py`/`generate_claims_bronze.py`'s synthetic data for a real source extract (S3/JDBC) once one exists — the validate/transform/curate stages don't need to change.
- Replace the drop+recreate writes with `MERGE INTO` / `INSERT OVERWRITE` to preserve Iceberg snapshot/time-travel history across runs.
- Add Great Expectations to the validate stages for richer expectation suites, mirroring the reference workshop's Module 05.
- Enable the schedule (`schedule_interval="@daily"` or similar) once the demo data volume/cadence story is finalized.
