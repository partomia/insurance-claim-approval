# Insurance Claim Processing API

See the [root README](../README.md) for setup instructions.

## API Documentation

When running locally, OpenAPI docs are at http://localhost:8000/docs

## Key Modules

- `models/` — 10 SQLAlchemy entities
- `services/` — Policy validation, RAG, fraud, decision engine, explainability
- `tasks/` — Celery parallel orchestration
- `routers/` — REST API endpoints

## Commands

```bash
uv run python seed.py              # Seed demo data + FAISS index
uv run celery -A tasks.celery_app worker --loglevel=info
uv run uvicorn main:app --reload
uv run pytest tests/ -v
```
