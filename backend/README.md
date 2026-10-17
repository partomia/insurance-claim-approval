# Insurance Claim Processing API

FastAPI backend of the claim app. Setup, environment and the API table: the
[root README](../README.md); every module: [`docs/backend-map.md`](../docs/backend-map.md).

## API Documentation

When running locally, OpenAPI docs are at http://localhost:8000/docs

## Key Modules

- `models/` — SQLAlchemy entities: customers, policies, claims, progress, audit, agents,
  insurer users, risk and profile signals, assistant memory
- `services/` — claim pipeline: policy validation, RAG (Chroma), evidence, fraud, decision
  engine, payout, explainability; `customer_trust_service.py` (Customer Trust Score),
  `llm_guard.py` (PII redaction and grounding check on LLM text),
  `approval_model_service.py` (mcc approval model, shadow scoring; off unless
  `APPROVAL_MODEL_MODE=shadow`)
- `routers/` — REST API: customer, agent and insurer portals, claims, policies, assistants
- `tasks/` — Celery orchestration (`CLAIM_PROCESSING_MODE=celery`)
- `scripts/` — seeding, Chroma indexing, lakehouse ingest and claim export, DB connection test

## Commands

```bash
uv sync --extra dev                                  # app + test dependencies
uv run python seed.py                                # demo data (--reset to start over)
uv run python scripts/ingest_policies.py             # policy documents into Chroma
uv run uvicorn main:app --reload
uv run celery -A tasks.celery_app worker --loglevel=info   # only for CLAIM_PROCESSING_MODE=celery
uv run pytest -q
```

Lakehouse (Cloudera, `LAKEHOUSE_DATABASE` set): `scripts/ingest_lakehouse.py` loads gold
policies, clauses and risk into SQLite + Chroma; `scripts/export_claims_to_lakehouse.py`
writes decided claims to the bronze layer. On Cloudera AI these run as jobs
(`mcc-lakehouse-ingest`, `mcc-export-claims` on federal; `cml/cli.sh lakehouse` on go01).
