# Architecture

## Three portals, one platform

The app serves three distinct audiences through one FastAPI backend:

| Portal | Audience | Auth entry | Key routers |
|--------|----------|------------|-------------|
| **Customer** | Policyholders filing/tracking claims | `/api/auth/*` | `assistant`, `claims`, `kyc`, `policy_connect`, `dashboard` |
| **Agent** (Expert Copilot) | Insurance experts triaging assigned claims | `/api/agent/auth/*` | `agent`, `agent_assistant`, `agents` |
| **Insurer** (admin) | Insurer back-office | `/api/insurer/auth/*` | `insurer`, `insurer_auth` |

Each portal has its own auth session table (`auth_session`,
`agent_auth_session`, `insurer_auth_session`) and its own dependency injector
(`get_current_customer`, `get_current_agent`, `get_current_insurer_user`) so
tokens never cross portals.

## Request → decision flow (customer path)

```
Customer submits claim
   │
   ▼
POST /api/claims/submit  (routers/claims.py)
   │  saves Claim + ClaimDocuments to DB
   ▼
services/claim_pipeline.py orchestrates:
   ├─ policy_validation       (services/policy_validation.py)
   ├─ rag_service.retrieve    (services/rag_service.py → Chroma)
   ├─ evidence_analysis       (services/evidence_analysis.py + OCR)
   ├─ fraud_detection         (services/fraud_detection.py)
   ├─ payout_calculation      (services/payout_calculation.py + LLM)
   └─ decision_engine.decide  (services/decision_engine.py)
        │
        ▼ writes ClaimDecision + FraudAssessment + AuditLog
POST-decision:
   • explainability            (services/explainability.py)
   • customer notified         (services/notification.py)
   • expert review queued if flagged (services/expert_queue_service.py)
```

Runtime mode is chosen by `CLAIM_PROCESSING_MODE`:

- `celery` — pipeline runs in `tasks/claim_tasks.py` on a Redis-backed worker.
- `sync` — pipeline runs inline in the request thread (used on Cloudera CML where Redis isn't reliable).
- `auto` — try Celery, fall back to sync if the broker is unreachable.

## Assistant / Copilot flow (customer & expert)

Both copilots share one memory layer (`assistant_memory_service.py`) built on
three tables: `assistant_sessions` → `assistant_threads` → `assistant_messages`.

```
User message
   │
   ▼
POST /api/assistant/chat            (customer)
POST /api/agent/assistant/chat      (expert)
   │
   ▼
resolve session (owner_type, owner_id, persona)
resolve thread  (thread_id ? claim_id ? default general)
   │
   ▼
load STM: recent N turns + running summary
load LTM: persona facts JSON on the session
build prompt: [LTM] [account/claim ctx] [RAG] [summary] [history] [user]
   │
   ▼
Groq LLM (services/llm_service.py) → structured reply
   │
   ▼
persist_exchange (user + assistant rows)
maybe_compact_thread → 1 LLM call → {summary, facts}
   ├─ update thread.summary_text
   └─ merge into session.long_term_memory_json
```

See [`assistant-memory.md`](./assistant-memory.md) for the full model.

## Deployment topology

Two supported shapes:

**Local / demo** (`./start.sh`):

```
[React (Vite)]  ── HTTP ──▶ [FastAPI (uvicorn)]
                                 ├── SQLite file
                                 ├── Chroma (embedded, local disk)
                                 └── (optional) Redis + Celery worker
```

**Docker Compose** (`docker compose up`):

```
[frontend]  [backend]  [worker]  [postgres]  [redis]
   ▲            │          │         ▲          ▲
   └── HTTP ────┘          └── DB & broker ─────┘
   (Chroma still embedded in backend container, persisted volume)
```

**Cloudera CML** — the `ROOT_PATH=/proxy/<port>` env var enables Swagger UI
behind the CML port proxy; `CLAIM_PROCESSING_MODE=sync` skips Redis.

## Data model (SQLAlchemy)

Grouped by concern (see `backend/models/*.py` for the columns):

| Group | Tables |
|-------|--------|
| **Identity** | `customers`, `policy_agents`, `insurer_users` |
| **Sessions** | `auth_sessions`, `agent_auth_sessions`, `insurer_auth_sessions` |
| **Product** | `policies`, `policy_documents`, `premium_payments`, `insurance_providers` |
| **Customer platform** | `customer_profiles` (KYC, saved contacts, dependents) |
| **Claims** | `claims`, `claim_documents`, `claim_progress_events`, `claim_decisions` |
| **Audit / risk** | `audit_logs`, `fraud_assessments`, `human_reviews` |
| **RAG** | `policy_clause_embeddings` (metadata mirror of Chroma vectors) |
| **Legacy chat** (read-only after v2) | `claim_chat_messages`, `customer_chat_messages`, `agent_chat_messages` |
| **Assistant memory v2** | `assistant_sessions`, `assistant_threads`, `assistant_messages` |

Legacy chat tables are still present so the one-time backfill
(`backfill_legacy_messages`) can migrate historical rows. After the first prod
boot completes the migration, flip `ASSISTANT_BACKFILL_ON_STARTUP=false`.

## AI surface

| Feature | Model / library | Cost knob |
|---------|-----------------|-----------|
| Coverage + fraud + payout analysis | Groq `openai/gpt-oss-120b` via `langchain_groq.ChatGroq` | `GROQ_MODEL` |
| Policy RAG | Chroma + OpenAI `text-embedding-3-small` (falls back to random embeddings if key missing) | `OPENAI_API_KEY`, `EMBEDDING_MODEL` |
| Copilot replies | Groq (`llm_service.invoke_assistant`) | Per-persona `max_tokens` constants in service |
| Compaction summary + LTM extraction | Groq (`llm_service.invoke_summarize`) | `ASSISTANT_SUMMARY_MAX_TOKENS`, `ASSISTANT_LTM_EXTRACT_MAX_TOKENS` |
| Evidence type check | Groq (`llm_service.validate_evidence_document`) | Gated by valid `GROQ_API_KEY` |

## Diagrams

See [`docs/diagrams/`](./diagrams/) — `01-system-architecture`,
`04-ai-agent-pipeline`, `05-data-flow`, `06-three-portal-model`,
`07-hybrid-ai-approach` (Mermaid `.mmd` sources + rendered PNGs).
