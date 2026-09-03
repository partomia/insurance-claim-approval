# AI-Powered Motor Vehicle Insurance Claim Processing System

Production-grade **motor-vehicle** insurance claim processing with FastAPI, Celery, Redis, Impala (CDP), Chroma RAG, motor-tuned fraud detection, own-damage / third-party payout split, total-loss detection, and a Confidence & Explainability Layer.

## Architecture

```
User → API Gateway (FastAPI) → Claim Orchestrator (Celery + Redis)
  → Parallel: Policy Validation | RAG Retrieval | Customer Profile | Evidence | Fraud
  → Decision Engine → Payout Calculation → Explainability Layer
  → Auto Approve/Reject | Human Review | Audit Log
```

## Quick Start (Docker)

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

- API: http://localhost:8000/docs
- Frontend: http://localhost:5173
- Demo login: `test@example.com` / `password123` / OTP: `112233`

## Quick Start (Local)

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
chmod +x start.sh
./start.sh
```

- API: http://localhost:8000/docs
- Frontend: http://localhost:5173
- Demo login: `test@example.com` / `password123` / OTP: `112233`

Optional: `START_CELERY=1 ./start.sh` if Redis is running. For Docker: `./start.sh docker`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/claims/submit` | Submit claim with documents (multipart) |
| GET | `/api/claims/{id}/status` | Claim status + decision summary |
| POST | `/api/claims/{id}/documents` | Upload supplemental documents |
| POST | `/api/claims/{id}/review` | Human review decision |
| GET | `/api/claims/{id}/audit` | Regulator-ready audit report |
| GET | `/api/policies/{policy_number}/summary` | Policy details |

## Decision Output Format

```json
{
  "claim_id": "CLM12345",
  "status": "APPROVED",
  "payable_amount": 125000,
  "own_damage_payable": 100000,
  "third_party_payable": 0,
  "gst_amount": 22500,
  "is_total_loss": false,
  "salvage_deduction": 0,
  "next_cycle_ncb_pct": 0,
  "fraud_score": 0.12,
  "confidence_score": 0.91,
  "retrieved_clauses": ["Section 4.2", "Section 7.1"],
  "reasoning": "Motor collision covered under own-damage; deductible and age-based depreciation applied...",
  "human_review_required": false
}
```

## Celery Tasks

- `validate_policy_task`
- `retrieve_policy_clauses_task`
- `analyze_evidence_task`
- `fraud_detection_task`
- `calculate_payout_task`
- `generate_decision_task`
- `notify_customer_task`

## Running Tests

```bash
cd backend
pytest tests/ -v
```

## Project Structure

```
backend/
├── models/          # SQLAlchemy models (10 entities)
├── services/        # AI agents & business logic
├── tasks/           # Celery task definitions
├── routers/         # FastAPI endpoints
├── scripts/         # Seed & FAISS ingest
└── tests/           # Unit tests
frontend/            # React + Vite UI
```

## Environment Variables

See [`backend/.env.example`](backend/.env.example) and [`frontend/.env.example`](frontend/.env.example). Key settings:

| Variable | Where | Purpose |
|----------|-------|---------|
| `GROQ_API_KEY` | backend | Groq API key for LLM agents in claim flow |
| `GROQ_MODEL` | backend | Default: `openai/gpt-oss-120b` |
| `CLAIM_PROCESSING_MODE` | backend | `sync` (local/CML), `celery` (Docker), or `auto` |
| `ROOT_PATH` | backend | Cloudera proxy prefix, e.g. `/proxy/7878` |
| `CORS_ORIGINS` | backend | Comma-separated frontend URLs allowed to call the API |
| `VITE_API_URL` | frontend | Backend base URL (set in Vercel env vars for production) |

### Cloudera + Vercel deployment

**Backend** (`backend/.env` on CML session):

```env
DATABASE_BACKEND=impala
IMPALA_HOST=go01-aws-rtdm-gateway.go01-dem.ylcu-atmi.cloudera.site
IMPALA_PORT=443
IMPALA_USE_SSL=true
IMPALA_AUTH_MECHANISM=GSSAPI
IMPALA_USE_HTTP_TRANSPORT=true
IMPALA_HTTP_PATH=go01-aws-rtdm/cdp-proxy-api/impala
ROOT_PATH=/proxy/7878
CORS_ORIGINS=https://icn-agents.vercel.app,http://localhost:5173
CLAIM_PROCESSING_MODE=sync
GROQ_API_KEY=your-key
```

**Frontend** (Vercel → Settings → Environment Variables):

```env
VITE_API_URL=https://YOUR-SESSION.ml-....cloudera.site/proxy/7878
```

Use the exact proxy URL from the CML **PORTS** tab (no trailing slash). Restart the backend after changing `.env`.

## Test Impala connection (local or CML)

```bash
cd backend
cp .env.example .env   # set IMPALA_* vars
pip install -e ".[dev]"
python scripts/test_impala_connection.py
python scripts/test_impala_connection.py --query "SHOW DATABASES"
```

For **LDAP** auth when Kerberos is unavailable locally, set in `backend/.env`:

```env
IMPALA_AUTH_MECHANISM=LDAP
IMPALA_USER=your-workload-username
IMPALA_PASSWORD=your-password
```

## Live Claim Processing

After submitting a claim, open the track page — it connects to `GET /api/claims/{id}/stream` (SSE) and shows each agent step live:

1. Policy Validation → 2. RAG Retrieval → 3. Customer Profile → 4. Evidence → 5. Fraud → 6. Groq Decision → 7. Payout

Use `CLAIM_PROCESSING_MODE=sync` on CML so the pipeline runs in-process without Celery.
