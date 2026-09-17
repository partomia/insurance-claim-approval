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

**Status: fully deployed and validated end-to-end** (both individual jobs
and the full Airflow-orchestrated DAG) on vcluster `cluster-pjq5xtvb`. See
[Live deployment](#live-deployment-reference) below for the exact resource
names, and [Gotchas we actually hit](#gotchas-we-actually-hit) for two real
bugs found while validating and how they were fixed.

```
cde/
├── jobs/
│   ├── generate/generate_bronze.py    ← Stage 1: synthesize raw policy data -> bronze
│   ├── validate/validate_bronze.py    ← Stage 2: data-quality gate (fails pipeline on bad data)
│   ├── transform/transform_silver.py  ← Stage 3: clean/dedupe/type-cast -> silver
│   └── curate/curate_gold.py          ← Stage 4: enrich + finalize -> gold (app-facing tables)
├── dags/
│   └── insurance_lakehouse_dag.py     ← Airflow DAG chaining the 4 jobs via CDEJobRunOperator
├── resources/
│   └── requirements.txt               ← CDE python-env deps (empty today — see below)
└── scripts/
    ├── deploy_jobs.sh                 ← Create/sync the CDE Repository + create the 4 Spark jobs
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
   4 Spark jobs from `deploy_jobs.sh` work on any vcluster).

## One-time setup (from scratch)

If you're deploying this fresh (not reusing the names below), edit the
`REPO_NAME` / `PYTHON_ENV` / job-name variables at the top of
`deploy_jobs.sh` and `deploy_dag.sh` first — pick a prefix that won't
collide with other users on a shared vcluster (this deployment uses an
`rsingh-` prefix for exactly that reason).

```bash
./cde/scripts/deploy_jobs.sh   # creates/syncs the Repository, the python-env, and the 4 Spark jobs
./cde/scripts/deploy_dag.sh    # registers the Airflow DAG job (sourced from the same Repository)
```

`deploy_jobs.sh`:
1. Creates a CDE **Repository** (`cde repository create --type` is implicit;
   `--url`/`--branch` point at this GitHub repo) if it doesn't already exist,
   then `cde repository sync`s it to the latest commit on `main`.
2. Creates/uploads a **python-env** Resource from `cde/resources/requirements.txt`
   (empty today — all 4 jobs use only PySpark). **This resource takes 1–3
   minutes to build** (CDE builds a container image from it) — running a job
   before it's `ready` fails with `cannot use resource '...' in status
   'building'`. Poll with:
   ```bash
   cde resource describe --name rsingh-insurance-lakehouse-python-env
   ```
3. Creates the 4 Spark jobs, each with `--mount-1-resource <repo>` and
   `--application-file <repo-relative-path>` (e.g.
   `cde/jobs/generate/generate_bronze.py`) — a Repository mount preserves
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
Takes ~10–15 min end-to-end (4 sequential Spark job cold-starts + Airflow overhead).

**One stage at a time, via CDE CLI** (faster feedback while iterating):
```bash
cde job run --name rsingh-insurance-generate-bronze  --wait
cde job run --name rsingh-insurance-validate-bronze  --wait
cde job run --name rsingh-insurance-transform-silver --wait
cde job run --name rsingh-insurance-curate-gold      --wait
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

The gold tables are the exact ones `cml/cli.sh lakehouse verify` already checks and Hue already queries — running this pipeline just replaces the hand-seeded 3 rows with ~60 pipeline-produced rows, no downstream changes needed.

All tables are `STORED AS ICEBERG` (`format-version=2`), written via `CREATE TABLE ... USING iceberg AS SELECT` (full drop+recreate each run — simplest for a demo pipeline; a production version would use `MERGE`/`INSERT OVERWRITE` to preserve Iceberg snapshot history instead).

## Config knobs

- `INSURANCE_N_POLICIES` (Airflow Variable, default `60`) — how many synthetic policies `generate_bronze.py` creates. Set via CDE Airflow UI → Admin → Variables, or `airflow variables set INSURANCE_N_POLICIES 200`.

## Roadmap

- **Phase 3** (next) — an app-side ingestion script pulling `insurance_lakehouse.policy_master`/`policy_clauses` into the app's SQLite + Chroma RAG index, so the live app's policy data originates from this pipeline instead of `backend/scripts/seed.py`'s synthetic generator.
- Swap `generate_bronze.py`'s synthetic data for a real source extract (S3/JDBC) once one exists — stages 2–4 don't need to change.
- Replace the drop+recreate writes with `MERGE INTO` / `INSERT OVERWRITE` to preserve Iceberg snapshot/time-travel history across runs.
- Add Great Expectations to `validate_bronze.py` for richer expectation suites, mirroring the reference workshop's Module 05.
- Enable the schedule (`schedule_interval="@daily"` or similar) once the demo data volume/cadence story is finalized.
