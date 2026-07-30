# ic_agents — Documentation

AI-powered insurance claim processing platform. FastAPI backend, React frontend,
Groq LLM for reasoning, Chroma for policy RAG, Celery/Redis for the claim
pipeline, SQLAlchemy on SQLite (dev) or Postgres (prod).

## Docs index

| File | What it covers |
|------|----------------|
| [`architecture.md`](./architecture.md) | High-level system diagram, request flow, deployment topology |
| [`backend-map.md`](./backend-map.md) | Every backend module and its role |
| [`assistant-memory.md`](./assistant-memory.md) | STM/LTM memory layer (deep dive) |
| [`frontend.md`](./frontend.md) | Frontend routes and components |
| [`env-reference.md`](./env-reference.md) | All environment variables, defaults, and when to change them |
| [`diagrams/`](./diagrams/) | Mermaid + PNG diagrams for architecture, data flow, portals, agent pipeline |

## Quick start

```bash
# 1. Config
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 2. Bring up the stack
./start.sh                     # local (uses SQLite by default)
# or
docker compose up --build      # Postgres + Redis + backend + frontend

# 3. Open
open http://localhost:8000/docs     # API (Swagger)
open http://localhost:5173          # frontend
```

Demo login: `test@example.com` / `password123` / OTP `112233`.

## Verify anything

```bash
cd backend
./.venv/bin/python -m pytest tests/ -q                                # full suite
./.venv/bin/python -m pytest tests/test_assistant_memory.py -v        # memory layer
./.venv/bin/python -c "from main import app; print('imports ok')"     # import lint
```
