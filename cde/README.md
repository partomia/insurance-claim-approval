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
`cde repository sync`, and every job picks up the new code with no
re-upload step.

```
cde/
├── jobs/
│   ├── generate/generate_bronze.py    ← Stage 1: synthesize raw policy data -> bronze
│   ├── validate/validate_bronze.py    ← Stage 2: data-quality gate (fails pipeline on bad data)
│   ├── transform/transform_silver.py  ← Stage 3: clean/dedupe/type-cast -> silver
│   └── curate/curate_gold.py          ← Stage 4: enrich + finalize -> gold (app-facing tables)
├── dags/
│   └── insurance_lakehouse_dag.py     ← Airflow DAG chaining the 4 jobs
├── resources/
│   └── requirements.txt               ← CDE python-env deps (empty today — see below)
└── scripts/
    ├── deploy_jobs.sh                 ← Create/sync the CDE Repository + create the 4 Spark jobs
    └── deploy_dag.sh                  ← Register the Airflow DAG (sourced from the same Repository)
```

## Source: CDE Repository, not uploaded files

`deploy_jobs.sh` creates a CDE **Repository** resource (`insurance-claim-approval-repo`) pointing at this GitHub repo on branch `main`, syncs it, then creates each job with `--mount-1-resource insurance-claim-approval-repo` and `--application-file cde/jobs/.../*.py` — the real repo-relative path, since a Repository mount preserves the directory structure (unlike a flat `files` Resource). The Airflow job (`deploy_dag.sh`) uses the same Repository via `--dag-file cde/dags/insurance_lakehouse_dag.py`.

**Day-2 workflow** — after any code change:
```bash
git push origin main
cde repository sync --name insurance-claim-approval-repo
# Spark jobs pick this up on their next run automatically.
# For the DAG file specifically, also re-run:
./cde/scripts/deploy_dag.sh
```

**Private repo?** Pass a GitHub Personal Access Token (repo:read scope):
```bash
GIT_CREDENTIAL=ghp_xxx ./cde/scripts/deploy_jobs.sh
```

## Python environment

`deploy_jobs.sh` also creates a separate CDE `python-env` Resource (`insurance-lakehouse-python-env`) from `cde/resources/requirements.txt` and attaches it to all 4 jobs via `--python-env-resource-name` — this stays a regular uploaded Resource since a Repository can't build a Python environment. It's intentionally empty right now — all 4 jobs use only PySpark, which the CDE Spark runtime already provides — but it's wired up so adding a real dependency later (Faker for richer synthetic data, Great Expectations for the validate stage, etc.) is just editing that one file and re-running `deploy_jobs.sh`, no job redefinition needed.

## Data flow

| Stage | Reads | Writes | Purpose |
|---|---|---|---|
| **generate** | — (synthesizes data) | `insurance_lakehouse_bronze.policy_master_raw`, `.policy_clauses_raw` | Stand-in for a real source extract; ~60 synthetic motor policies + clause text |
| **validate** | bronze | — (pass/fail only) | Null/duplicate/referential-integrity checks; `sys.exit(1)` fails the DAG run if violated |
| **transform** | bronze | `insurance_lakehouse_silver.policy_master`, `.policy_clauses` | Trim/standardize strings, cast types, dedupe by `policy_number` |
| **curate** | silver | `insurance_lakehouse.policy_master`, `.policy_clauses` | Adds `risk_band` + `premium_to_coverage_pct`; writes to the **same gold tables Phase 1 created** |

The gold tables are the exact ones `cml/cli.sh lakehouse verify` already checks and Hue already queries — running this pipeline just replaces the hand-seeded 3 rows with ~60 pipeline-produced rows, no downstream changes needed.

All tables are `STORED AS ICEBERG` (`format-version=2`), written via `CREATE TABLE ... USING iceberg AS SELECT` (full drop+recreate each run — simplest for a demo pipeline; a production version would use `MERGE`/`INSERT OVERWRITE` to preserve Iceberg snapshot history instead).

## Deploy

Requires the CDE CLI installed and configured (`~/.cde/config.yaml` with your vcluster endpoint). No local clone of this repo is needed on the machine running the CLI — `deploy_jobs.sh` just needs `cde/resources/requirements.txt` locally to upload the python-env; everything else is pulled by CDE directly from GitHub.

```bash
./cde/scripts/deploy_jobs.sh   # creates the Repository + insurance-generate-bronze, -validate-bronze, -transform-silver, -curate-gold
./cde/scripts/deploy_dag.sh    # registers insurance_lakehouse_pipeline in CDE Airflow
```

## Run

**Whole pipeline, via Airflow:**
CDE Airflow UI → DAGs → `insurance_lakehouse_pipeline` → trigger manually (it's `schedule_interval=None` by default — flip to `"@daily"` in `dags/insurance_lakehouse_dag.py` once you're happy with it).

**One stage at a time, via CDE CLI** (useful while iterating):
```bash
cde job run --name insurance-generate-bronze  --wait
cde job run --name insurance-validate-bronze  --wait
cde job run --name insurance-transform-silver --wait
cde job run --name insurance-curate-gold      --wait
```

**Check logs for a run:**
```bash
cde run list --job-name insurance-generate-bronze
cde run logs --id <run-id> --type driver/stdout
```

## Verify the result

Same commands as Phase 1, now backed by pipeline-produced data:
```bash
bash cml/cli.sh lakehouse verify
```
or in Hue (Impala SQL editor):
```sql
SELECT risk_band, COUNT(*), AVG(premium_to_coverage_pct)
FROM insurance_lakehouse.policy_master
GROUP BY risk_band;
```
(If Hue doesn't see the refreshed data, run `INVALIDATE METADATA;` first — same catalog-cache gotcha as Phase 1.)

## Config knobs

- `INSURANCE_N_POLICIES` (Airflow Variable, default `60`) — how many synthetic policies `generate_bronze.py` creates. Set via CDE Airflow UI → Admin → Variables, or `airflow variables set INSURANCE_N_POLICIES 200`.

## Roadmap

- **Phase 3** (next) — an app-side ingestion script pulling `insurance_lakehouse.policy_master`/`policy_clauses` into the app's SQLite + Chroma RAG index, so the live app's policy data originates from this pipeline instead of `backend/scripts/seed.py`'s synthetic generator.
- Swap `generate_bronze.py`'s synthetic data for a real source extract (S3/JDBC) once one exists — stages 2–4 don't need to change.
- Replace the drop+recreate writes with `MERGE INTO` / `INSERT OVERWRITE` to preserve Iceberg snapshot/time-travel history across runs.
- Add Great Expectations to `validate_bronze.py` for richer expectation suites, mirroring the reference workshop's Module 05.
