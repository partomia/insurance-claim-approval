# Backend map — which file has what

Root of the app is `backend/`. Everything below is relative to that root.

## Top level

| File | Role |
|------|------|
| `main.py` | FastAPI app. Wires all routers, runs `ensure_schema()` on import, mounts CORS, sets `root_path` for CML proxy |
| `config.py` | `Settings` (pydantic-settings). Loads `.env`. Every env var lives here — see [`env-reference.md`](./env-reference.md) |
| `database.py` | SQLAlchemy `engine`, `SessionLocal`, `Base`, `get_db()` FastAPI dependency |
| `db_init.py` | `ensure_schema()` — create tables + additive SQLite migrations + one-time legacy → assistant-memory backfill (gated by `ASSISTANT_BACKFILL_ON_STARTUP`) |
| `dependencies.py` | `get_current_customer`, `get_current_agent`, JWT helpers, password hashing |
| `schemas/__init__.py` | All Pydantic request/response models (one file) |
| `seed.py` / `scripts/seed*.py` | Dev-only demo data seeders |
| `pyproject.toml` / `.venv/` | Python deps |

## `routers/` — HTTP surface

| Router | Prefix | Purpose |
|--------|--------|---------|
| `auth.py` | `/api/auth` | Customer signup/login, JWT refresh, OTP |
| `assistant.py` | `/api/assistant` | Customer copilot chat (`/chat`, `/threads`) |
| `claims.py` | `/api/claims` | Submit / list / documents / audit / insights / per-claim chat |
| `kyc.py` | `/api/kyc` | Doc upload, mobile OTP, face verification stubs |
| `policies.py` | `/api/policies` | Policy list / detail / summary |
| `policy_connect.py` | `/api/policy-connect` | Onboard external policies with fake insurer OTP |
| `dashboard.py` | `/api/dashboard` | Customer home dashboard aggregates |
| `agent.py` | `/api/agent` | Expert Copilot assigned queue, review actions |
| `agent_auth.py` | `/api/agent/auth` | Agent signup/login (separate token store) |
| `agent_assistant.py` | `/api/agent/assistant` | Expert copilot chat (`/chat`) |
| `agents.py` | `/api/agents` | Admin: agent CRUD |
| `insurer.py` / `insurer_auth.py` | `/api/insurer/*` | Insurer back-office (approve/reject/audit) |
| `rag.py` | `/api/rag` | Admin: reindex Chroma, inspect chunks |

## `services/` — business logic (one module per concern)

### Claim pipeline (in dependency order)

| File | Responsibility |
|------|----------------|
| `claim_service.py` | Create/read `Claim`, ownership checks |
| `orchestrator.py` | Kicks off Celery task or sync pipeline based on `CLAIM_PROCESSING_MODE` |
| `claim_pipeline.py` | Runs the pipeline stages end-to-end and writes `ClaimDecision` |
| `policy_validation.py` | Policy active + coverage type + waiting period checks |
| `rag_service.py` | Chroma client wrapper, retrieve() top-k policy clauses |
| `policy_context_service.py` | Extract policy profile + key sections from documents |
| `evidence_analysis.py` | OCR + LLM validation of uploaded documents |
| `evidence_service.py` | Filesystem read/write of uploaded evidence blobs |
| `ocr_service.py` | Tesseract / pdfplumber wrapper |
| `fraud_detection.py` | Rule-based + LLM fraud scoring |
| `llm_payout_service.py` | LLM-extracted deductible / co-pay / cap parameters |
| `payout_calculation.py` | Deterministic payout math from those parameters |
| `decision_engine.py` | Combine coverage + fraud + payout → status + review flag |
| `explainability.py` | Regulator-ready reasoning string |
| `customer_profile.py` | Customer risk profile (prior claims, tenure, signals) |
| `policy_service.py` | Policy CRUD + document indexing hooks |
| `notification.py` | Email/SMS stubs |
| `progress_service.py` | Emit `ClaimProgressEvent` rows for UI timeline |

### Assistant / copilot layer

| File | Responsibility |
|------|----------------|
| `assistant_memory_service.py` | **STM + LTM memory layer.** Sessions/threads/messages, compaction, fact merging, backfill. See [`assistant-memory.md`](./assistant-memory.md) |
| `assistant_response_service.py` | Prompt templates, intent detection, reply-shape normalization, structured fallbacks |
| `claim_assistant_service.py` | Per-claim customer copilot (uses memory + response services) |
| `universal_assistant_service.py` | Cross-claim customer copilot (RAG + account + memory) |
| `agent_assistant_service.py` | Expert copilot with focus detection (policy/claim/document/customer) |
| `llm_service.py` | Groq client. `invoke`, `invoke_assistant`, `invoke_summarize`, `invoke_json`, plus domain wrappers (`analyze_incident_coverage`, `analyze_fraud_risk`, `extract_payout_parameters`, `validate_evidence_document`, …) |

### Expert workflow

| File | Responsibility |
|------|----------------|
| `expert_queue_service.py` | Assign flagged claims to available experts |
| `expert_review_service.py` | Expert accept/reject/request-info actions |
| `document_request_service.py` | Follow-up doc requests to customer |
| `escalation_service.py` | Escalate stuck claims |
| `agent_service.py` | Expert home queue + policy-requirements builder |

### Aggregation / read models

| File | Responsibility |
|------|----------------|
| `analysis_service.py` | Format `ClaimDecision` into customer-facing dict/text for UI + assistant |
| `dashboard_service.py` | Customer dashboard aggregates |
| `insights_service.py` | Track-claim insights payload |
| `insurer_service.py` / `insurer_demo_service.py` | Insurer views + demo data |
| `document_serving.py` | Signed URLs / stream evidence files |

## `models/` — SQLAlchemy tables

One file per aggregate. `models/__init__.py` re-exports the lot.

| File | Tables |
|------|--------|
| `customer.py` | `customers` (+ `assistant_messages` back-ref to legacy) |
| `auth_session.py` | `auth_sessions` |
| `agent_auth_session.py` | `agent_auth_sessions` |
| `insurer_auth_session.py` | `insurer_auth_sessions` |
| `insurer_user.py` | `insurer_users` |
| `policy_agent.py` | `policy_agents` |
| `policy.py` | `policies`, `policy_documents`, `premium_payments`, enums |
| `platform.py` | `customer_profiles`, `insurance_providers`, `KYCStatus` |
| `claim.py` | `claims`, `claim_documents`, enums |
| `claim_progress.py` | `claim_progress_events` |
| `audit.py` | `audit_logs`, `claim_decisions`, `fraud_assessments`, `human_reviews` |
| `embeddings.py` | `policy_clause_embeddings` |
| `chat.py` | Legacy `claim_chat_messages`, `customer_chat_messages`, `agent_chat_messages` (read-only after v2 backfill) |
| `assistant_memory.py` | **v2 memory:** `assistant_sessions`, `assistant_threads`, `assistant_messages` + enums (`AssistantPersona`, `AssistantOwnerType`, `AssistantThreadType`). Composite index `ix_assistant_messages_thread_created` |

## `tasks/` — Celery

| File | Role |
|------|------|
| `celery_app.py` | Broker/backend config from Redis URL |
| `claim_tasks.py` | `process_claim_task` — wraps `claim_pipeline` for async execution |

## `agents/` — workflow graph (LangGraph-style, opt-in)

| File | Role |
|------|------|
| `state.py` | Shared state dataclass |
| `workflow.py` | Node definitions for an experimental agent workflow |

## `rag/`

| File | Role |
|------|------|
| `chroma_client.py` | Lazy Chroma client factory (respects `CHROMA_DB_PATH`) |
| `chroma_store.py` | `chroma_store` singleton with `_client`, `_collection`, `_embeddings`. Reset per-test in `conftest.py` |

## `alembic/` (scaffolded but unused)

The repo uses `Base.metadata.create_all()` + additive migrations in `db_init.py`
instead of Alembic revisions. `alembic/env.py` is ready if you want to switch.

## `tests/`

| File | Coverage |
|------|----------|
| `conftest.py` | `db_session` fixture (in-memory SQLite, StaticPool), `client` TestClient, Chroma isolation |
| `test_agent_api.py` | Agent queue + assignment endpoints |
| `test_agent_assistant.py` | Expert copilot (focus detection, reply, history) |
| `test_agent_auth.py` | Agent login |
| `test_assign_api.py` | Claim → expert assignment |
| `test_assistant_memory.py` | STM/LTM regressions (B1–B5, M1/M2/M4/M6) |
| `test_assistant_response.py` | Prompt templates, intent detection |
| `test_auth_profile.py` | Customer auth + profile |
| `test_chroma_rag.py` | RAG round trip |
| `test_claim_pipeline.py` | End-to-end pipeline |
| `test_claims_api.py` | Claims REST |
| `test_dashboard_api.py` | Dashboard aggregates |
| `test_decision_engine.py` | Decision matrix (⚠ 1 pre-existing failure unrelated to memory work) |
| `test_document_request_service.py` | Expert-driven doc requests |
| `test_evidence_mismatch.py` | Evidence type-mismatch logic |
| `test_evidence_replace_api.py` | Replace/append evidence |
| `test_expert_review.py` | Expert review actions |
| `test_fraud_scoring.py` | Rule scoring |
| `test_insurer_api.py` | Insurer approve/reject |
| `test_payout.py` | Deductible/co-pay math |
| `test_rag_service.py` | Retrieval scoring |

## `frontend/`

Vite + React + Tailwind. See [`frontend.md`](./frontend.md).
