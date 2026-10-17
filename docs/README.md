# ic_agents — Documentation

AI-powered motor insurance claim processing. FastAPI backend, React frontend, Groq (or an
OpenAI-compatible endpoint such as Cloudera AI Inference) for reasoning, Chroma for policy
RAG, an in-process or Celery/Redis claim pipeline, SQLAlchemy on SQLite. On Cloudera the
project adds Motor Claim Copilot ("mcc"): a governed claims lakehouse and a trained approval
model scoring claims in shadow mode. Start with the [root README](../README.md).

## Docs index

| File | What it covers |
|------|----------------|
| [`../PLAN.md`](../PLAN.md) | The mcc plan: sources, layers, KPIs, model, gates, phases |
| [`DEMO_RUNBOOK.md`](./DEMO_RUNBOOK.md) | mcc on `federal-cdp-env`: links, logins, demo flow, start/stop, troubleshooting |
| [`PROJECT_LOG.md`](./PROJECT_LOG.md) | Every live action of the mcc build, with outcomes |
| [`REUSE_INVENTORY.md`](./REUSE_INVENTORY.md) | Files copied from sibling projects and what changed |
| [`steps-to-demo-execution.md`](./steps-to-demo-execution.md) | go01: click/command runbook for the OLTP + lakehouse demo (resources assumed running) |
| [`plans/step5-approval-model-plan.md`](./plans/step5-approval-model-plan.md) | The original approval-model design (CDE features → CAI training → model endpoint → shadow mode); built as mcc |
| [`architecture.md`](./architecture.md) | The app: system diagram, request flow, deployment topology |
| [`backend-map.md`](./backend-map.md) | Every backend module and its role |
| [`assistant-memory.md`](./assistant-memory.md) | STM/LTM memory layer (deep dive) |
| [`frontend.md`](./frontend.md) | Frontend routes and components |
| [`env-reference.md`](./env-reference.md) | App environment variables, defaults, and when to change them |
| [`diagrams/`](./diagrams/) | Mermaid + PNG diagrams for architecture, data flow, portals, agent pipeline |
| [`demo-assets/claim-docs/`](./demo-assets/claim-docs/) | Sample claim documents for uploading in a demo |

Per-area guides: [`../backend/README.md`](../backend/README.md),
[`../frontend/README.md`](../frontend/README.md), [`../cml/README.md`](../cml/README.md)
(Cloudera AI), [`../cde/README.md`](../cde/README.md) (Cloudera Data Engineering).

## Quick start

```bash
# 1. Config
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 2. Bring up the stack
./start.sh                     # local, SQLite
# or
docker compose up --build      # Redis + API + Celery worker + frontend

# 3. Open
open http://localhost:8000/docs     # API (Swagger)
open http://localhost:5173          # frontend
```

Demo login: `test@example.com` / `password123` / OTP `112233` (all logins: the
[runbook](./DEMO_RUNBOOK.md)).

## Verify anything

```bash
pytest -q                                                   # repo root: lakehouse, ML, governance, ops
cd backend && uv sync --extra dev
uv run pytest -q                                            # the app
uv run pytest tests/test_assistant_memory.py -v             # memory layer
uv run python -c "from main import app; print('imports ok')" # import check
cd ../frontend && npm run build                             # type check + SPA build
```
