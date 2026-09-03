# CrewAI Migration Plan — Motor Claim Copilot

**Owner:** backend
**Target:** replace the ad-hoc `services/claim_pipeline.py` orchestration + legacy `agents/workflow.py` LangGraph pipeline with a **CrewAI Flow** that composes typed agents, tasks, and a stateful flow.
**Non-goals:** replacing the two conversational assistants (Customer / Expert Copilot) — those keep their current Groq + memory implementation. This plan is only for the **claim adjudication pipeline**.

---

## Context

Today the backend has two overlapping orchestration paths:

1. `backend/services/claim_pipeline.py` — a hand-written `ThreadPoolExecutor` that runs 4 analysis services in parallel, then serially runs fraud → escalation → explainability → decision → payout → LLM reasoning.
2. `backend/agents/workflow.py` — a legacy LangGraph `StateGraph` with 5 sequential nodes (documented in `docs/agents/AGENTS.md` as "Agent #14, legacy").

Both call into the same underlying services (`PolicyValidationService`, `RAGService`, `EvidenceAnalysisService`, `FraudDetectionService`, `EscalationService`, `DecisionEngine`, `PayoutCalculationService`, `LLMPayoutService`, `LLMService`, `ExplainabilityService`).

**Goal:** consolidate on **CrewAI Flow** (`crewai.flow`) so we get:
- First-class `@start` / `@listen` / `@router` decorators for the parallel-then-sequential shape.
- Typed Pydantic state that replaces the untyped `dict` currently threaded through the pipeline.
- Native agent/task/tool abstractions that align with the 14-agent catalogue we already documented.
- Built-in observability (flow visualization, traces).
- Removal of the deprecated LangGraph path.

The conversational assistants stay on Groq + `AssistantMemory` — they're chat-shaped, not pipeline-shaped, and CrewAI's crew abstraction adds no value there.

---

## Step 1 — Design CrewAI Flow architecture

Design the target CrewAI Flow shape: which of the 14 agents map to CrewAI `Agent` objects vs stay as `Tool` implementations, what the shared `FlowState` (Pydantic) looks like, and how `@start` / `@listen(and_(...))` / `@router` decorators recreate the current parallel-then-sequential graph. Produce an architecture doc under `docs/agents/CREWAI_ARCHITECTURE.md` covering: agent → CrewAI role mapping, tool boundaries (which services become `@tool` functions vs stay as plain Python), state schema, and error/retry policy. Compare CrewAI Flow vs Crew (task-list) and justify Flow for this parallel-then-serial workload.

## Step 2 — Add crewai dependency and scaffold module

Add `crewai` (and `crewai-tools` if needed) to `backend/pyproject.toml` under the main dependency set with a pinned version. Create `backend/crew/` package with empty modules: `__init__.py`, `state.py`, `agents.py`, `tools.py`, `flow.py`. No behavior yet — this step exists purely to introduce the dependency and package layout so subsequent test-first steps have somewhere to write.

## Step 3 — Define FlowState Pydantic model

Implement the `ClaimFlowState` Pydantic model in `backend/crew/state.py` that replaces the untyped dict threaded through `claim_pipeline.py`. Fields cover claim_id, per-stage result blocks (policy_validation, rag_retrieval, customer_profile, evidence_analysis, fraud_detection, escalation, decision, payout, explainability), and pipeline_run_id. Every field is optional with a sensible default so the state can be constructed empty at flow start.

## Step 4 — Wrap analysis services as CrewAI tools

Wrap `PolicyValidationService`, `RAGService`, `CustomerProfileService`, `EvidenceAnalysisService`, `FraudDetectionService`, `EscalationService`, `DecisionEngine`, `PayoutCalculationService`, `LLMPayoutService`, `ExplainabilityService`, and the relevant `LLMService` methods as `crewai.tools.tool` functions in `backend/crew/tools.py`. Each tool takes a claim_id (and any prior-stage result it needs) and returns a typed Pydantic dataclass. Preserve the current per-service DB session pattern — tools open their own `SessionLocal()` and close it in `finally`.

## Step 5 — Define CrewAI Agents

Define one `crewai.Agent` per production agent from `docs/agents/AGENTS.md` (excluding the two conversational copilots and the legacy LangGraph workflow) in `backend/crew/agents.py`. Each agent gets a role, goal, backstory (copy verbatim from `AGENTS.md`), the tools it should have access to (from Step 4), and its LLM configured to point at Groq. Agents that are pure rules engines (Policy Validator, Customer Profile, Decision Engine, Explainability) get an empty tools list plus a `allow_delegation=False` flag so they can only execute their assigned function.

## Step 6 — Implement CrewAI Flow with parallel fan-out

Build the `ClaimFlow(Flow[ClaimFlowState])` class in `backend/crew/flow.py`. `@start` publishes the "claim received" progress event and returns claim_id. Four `@listen(...)` methods run policy validation, RAG retrieval, customer profiling, and evidence analysis in parallel using `asyncio.gather` internally. A `@listen(and_(policy, rag, customer, evidence))` gate runs fraud detection once all four have completed. Subsequent `@listen` steps run escalation → explainability → decision. A `@router` splits on decision.status → APPROVED runs payout + LLM reasoning; other terminal states skip to notification. Every step publishes to `progress_service` exactly like the current pipeline so the frontend SSE stream stays identical.

## Step 7 — Migrate database writes and audit logging

Ensure every DB write currently performed inside `claim_pipeline.py` (claim.status transitions, `pipeline_run_id` bump, escalation flags, evidence issues, `HumanReview` insert, expert assignment) is preserved inside the CrewAI Flow. Emit the same `PARALLEL_ANALYSIS_COMPLETE` and `DECISION_GENERATED` audit-log entries. This step is intentionally paired with `database-reviewer` because the audit trail is regulator-facing.

## Step 8 — Write parity tests against the old pipeline

Add tests under `backend/tests/crew/test_flow_parity.py` that seed a claim, run the legacy `run_claim_pipeline()` and the new `ClaimFlow().kickoff()` against separate DB rows, and assert the outputs are equivalent on: final status, payable_amount (± cents rounding), fraud_score, confidence_score, escalation_flags (as a set), and human_review_required. Include 6 seed scenarios covering: happy-path approve, expired policy reject, evidence mismatch → pending review, high fraud → pending review, total-loss → pending review, and large claim over threshold → pending review.

## Step 9 — Wire the FastAPI router and Celery task to the new flow

Switch `backend/routers/claims.py` (submission endpoint) and `backend/tasks/claim_tasks.py` (Celery worker) to invoke `ClaimFlow().kickoff(inputs={"claim_id": …})` in place of `run_claim_pipeline(claim_id)`. Keep the old `run_claim_pipeline` function importable behind a `settings.use_legacy_pipeline` feature flag for one release so we can roll back if production surfaces a regression.

## Step 10 — Delete legacy LangGraph workflow

Once Step 8 parity tests are green and Step 9 has shipped behind the feature flag with the flag defaulting to the new flow, delete `backend/agents/workflow.py`, `backend/agents/state.py`, and the `backend/agents/__init__.py` re-exports. Remove `langgraph` from `pyproject.toml` if nothing else uses it. Grep the codebase for any remaining imports of `claim_agent_executor` and remove them.

## Step 11 — Update AGENTS.md documentation

Rewrite `docs/agents/AGENTS.md` so the flow diagram and per-agent entries reflect the CrewAI Flow. The 14-agent catalogue becomes 12 (the legacy LangGraph entry is gone; the Claim Orchestrator becomes the CrewAI Flow class). Add a "How to run the flow locally" section with a `python -m backend.crew.flow` runnable that visualizes the graph. Keep the manager/conversational/tool-calling type labels.

## Step 12 — End-to-end verification

Run the full user flow through the app: submit a motor claim via `/claim` in the frontend → verify SSE progress events fire in the same order → verify the final decision and payout match a known-good baseline → verify the audit trail page renders without changes. Also run `pytest backend/tests/crew` and confirm the parity suite is green.

---

## Acceptance criteria (whole plan)

- `backend/crew/flow.py::ClaimFlow` produces bit-identical decisions to `run_claim_pipeline` on the 6 seed scenarios (Step 8).
- No import of `langgraph`, `claim_agent_executor`, or `backend.agents.workflow` remains in the codebase (Step 10).
- `docs/agents/AGENTS.md` accurately describes the CrewAI Flow (Step 11).
- The submission-to-decision path over SSE still emits the same event names and payload shape the frontend consumes (Step 6, Step 12).

## Out of scope

- Migrating the Customer Copilot Assistant or Expert Copilot Assistant to CrewAI — they remain on the current Groq + `AssistantMemory` implementation.
- Replacing Groq with another LLM provider.
- Frontend changes — the SSE contract is preserved so no frontend edit is required.
- Adding new decision rules or new fraud signals — this is a refactor, not a feature add.
