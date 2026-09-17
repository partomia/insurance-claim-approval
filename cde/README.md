# Insurance Lakehouse Medallion Pipeline (CDE)

Phase 2 of the datalakehouse story: a real bronze → silver → gold Spark
pipeline on Cloudera Data Engineering (CDE), orchestrated with Airflow,
replacing Phase 1's hand-seeded Iceberg tables (`cml/cli.sh lakehouse seed`)
with a proper pipeline. Same pattern as
[`Cloudera-CDE-Workshop-with-Orchestration-and-CI-CD`](https://github.com/partomia/Cloudera-CDE-Workshop-with-Orchestration-and-CI-CD)
— CDE file resources + `cde job create --type spark`, chained via
`CDEJobRunOperator` in an Airflow DAG.

```
cde/
├── jobs/
│   ├── generate/generate_bronze.py    ← Stage 1: synthesize raw policy data -> bronze
│   ├── validate/validate_bronze.py    ← Stage 2: data-quality gate (fails pipeline on bad data)
│   ├── transform/transform_silver.py  ← Stage 3: clean/dedupe/type-cast -> silver
│   └── curate/curate_gold.py          ← Stage 4: enrich + finalize -> gold (app-facing tables)
├── dags/
│   └── insurance_lakehouse_dag.py     ← Airflow DAG chaining the 4 jobs
└── scripts/
    ├── deploy_jobs.sh                 ← Upload jobs + create CDE Job defs
    └── deploy_dag.sh                  ← Upload + register the Airflow DAG
```

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

Requires the CDE CLI installed and configured (`~/.cde/config.yaml` with your vcluster endpoint — see the reference workshop repo's Part 0 setup if you need this from scratch).

```bash
git clone <this-repo>   # or pull, if already cloned in your CDE dev environment
cd loan-approval

./cde/scripts/deploy_jobs.sh   # creates insurance-generate-bronze, -validate-bronze, -transform-silver, -curate-gold
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
