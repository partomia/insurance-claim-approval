# Motor Claim Copilot — Agent Catalogue

> **Platform:** Motor Claim Copilot  
> **Stack:** FastAPI · CrewAI Flow · LangChain (Groq wrapper) · Groq (llama-3) · ChromaDB · PostgreSQL  
> **Last updated:** 2026-08-13
>
> **Orchestration:** The claim adjudication pipeline runs through a **CrewAI Flow** (`backend/crew/flow.py`), gated by `settings.use_crewai_flow`. The legacy `services/claim_pipeline.py` remains as a fallback for one release. The legacy LangGraph workflow (`backend/agents/workflow.py`) is scheduled for removal — see [`docs/plans/crewai-migration-plan.md`](../plans/crewai-migration-plan.md).

---

## Table of Contents

1. [Agent Overview](#agent-overview)
2. [Agent Profiles](#agent-profiles)
   - [Claim Orchestrator](#1-claim-orchestrator)
   - [Policy Validator Agent](#2-policy-validator-agent)
   - [RAG Retrieval Agent](#3-rag-retrieval-agent)
   - [Customer Profile Agent](#4-customer-profile-agent)
   - [Evidence Analysis Agent](#5-evidence-analysis-agent)
   - [Fraud Detection Agent](#6-fraud-detection-agent)
   - [Escalation Evaluator Agent](#7-escalation-evaluator-agent)
   - [Decision Engine Agent](#8-decision-engine-agent)
   - [Payout Calculation Agent](#9-payout-calculation-agent)
   - [LLM Reasoning Agent](#10-llm-reasoning-agent)
   - [Explainability Agent](#11-explainability-agent)
   - [Customer Copilot Assistant](#12-customer-copilot-assistant)
   - [Expert Copilot Assistant](#13-expert-copilot-assistant)
   - [LangGraph Claim Workflow (Legacy)](#14-langgraph-claim-workflow-legacy)
3. [Agent Interaction Flow](#agent-interaction-flow)
4. [Data Flow Diagram](#data-flow-diagram)

---

## Agent Overview

| # | Agent Name | Type | LLM | File |
|---|---|---|---|---|
| 1 | Claim Orchestrator (CrewAI Flow) | Manager | — | `crew/flow.py` (new) · `services/claim_pipeline.py` (legacy fallback) |
| 2 | Policy Validator Agent | Tool-calling | — | `services/policy_validation.py` |
| 3 | RAG Retrieval Agent | Tool-calling | Groq | `services/rag_service.py` |
| 4 | Customer Profile Agent | Tool-calling | — | `services/customer_profile.py` |
| 5 | Evidence Analysis Agent | Tool-calling | Groq (tie-break) | `services/evidence_analysis.py` |
| 6 | Fraud Detection Agent | Tool-calling | Groq | `services/fraud_detection.py` |
| 7 | Escalation Evaluator Agent | Tool-calling | Groq | `services/escalation_service.py` |
| 8 | Decision Engine Agent | Tool-calling | — | `services/decision_engine.py` |
| 9 | Payout Calculation Agent | Tool-calling | Groq | `services/payout_calculation.py` + `services/llm_payout_service.py` |
| 10 | LLM Reasoning Agent | Tool-calling | Groq | `services/llm_service.py` |
| 11 | Explainability Agent | Tool-calling | — | `services/explainability.py` |
| 12 | Customer Copilot Assistant | Conversational | Groq | `services/universal_assistant_service.py` |
| 13 | Expert Copilot Assistant | Conversational | Groq | `services/agent_assistant_service.py` |
| 14 | LangGraph Claim Workflow | Manager (legacy) | GPT-4o | `agents/workflow.py` |

---

## Agent Profiles

---

### 1. Claim Orchestrator (CrewAI Flow)

| Field | Detail |
|---|---|
| **Name** | Claim Orchestrator (`ClaimFlow`) |
| **Type** | 🟣 Manager Agent — CrewAI `Flow[ClaimFlowState]` |
| **Role** | Top-level pipeline coordinator implemented as a CrewAI Flow. `@start` marks the claim `PROCESSING`; four `@listen(claim_received)` methods run in parallel (policy validation, RAG retrieval, customer profile, evidence analysis); `@listen(and_(all four))` gates fraud detection; a final `@listen(run_fraud_detection)` runs escalation → explainability → decision → payout → LLM reasoning. |
| **Backstory** | Original implementation used a hand-rolled `ThreadPoolExecutor` in `services/claim_pipeline.py`. Migrating to CrewAI Flow gave first-class parallel-fan-out decorators, typed Pydantic state (`ClaimFlowState`), native agent/task/tool abstractions aligned with this catalogue, and native flow visualization. The legacy path remains available behind `settings.use_crewai_flow=False` for one release. |
| **Goal** | Execute the complete claim processing pipeline for a given `claim_id`; produce `status`, `payable_amount`, `confidence_score`, and `reasoning`; update the database; and notify the customer — with the SSE progress-event contract identical to the legacy pipeline. |
| **LLM** | None (pure coordination logic; child agents own their own LLM usage) |
| **Tools / Sub-agents called** | Policy Validator · RAG Retrieval · Customer Profile · Evidence Analysis (parallel via `@listen(claim_received)`) · Fraud Detection · Escalation Evaluator · Decision Engine · Payout Calculation · Explainability · LLM Reasoning · Notification Service · Expert Assignment Service |
| **State** | `crew/state.py::ClaimFlowState` — Pydantic model with one optional block per stage |
| **Feature flag** | `settings.use_crewai_flow` (default `False`); flip to `True` in `.env` to route through the Flow |
| **Source** | `backend/crew/flow.py::ClaimFlow`, `crew/state.py`, `crew/tools.py`, `crew/agents.py` |

---

### 2. Policy Validator Agent

| Field | Detail |
|---|---|
| **Name** | Policy Validator Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Checks whether the submitted motor claim is eligible under the associated policy |
| **Backstory** | Not every claim can proceed — a lapsed policy, unpaid premium, or an incident that falls under a listed exclusion must be caught before any further analysis wastes compute. This agent is purpose-built to act as the first hard gate. |
| **Goal** | Return `eligible`, `policy_expired`, `premium_unpaid`, `incident_excluded`, `violations[]`, and `policy_match_score` for the claim |
| **LLM** | None |
| **Tools** | `SQLAlchemy DB` — queries `Policy`, `PremiumPayment` tables; checks expiry date, payment status, and policy exclusions list |
| **Source** | `backend/services/policy_validation.py` |

---

### 3. RAG Retrieval Agent

| Field | Detail |
|---|---|
| **Name** | RAG Retrieval Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Semantic search over indexed motor policy documents; returns the most relevant clauses for the incident |
| **Backstory** | Motor insurance policies are dense legal documents. When a claim arrives, the adjudicator needs to know exactly which section of the policy applies — own-damage clause, third-party liability, exclusions, etc. This agent embeds the incident query and retrieves the top-k matching clauses from ChromaDB, then uses the LLM to confirm coverage. |
| **Goal** | Return `retrieved_clauses[]`, `clause_clarity_score`, and `llm_coverage` (is_covered, confidence, summary) for the claim incident |
| **LLM** | Groq (`llama-3`) via `LLMService.analyze_incident_coverage()` — used to assess whether the retrieved clauses actually cover the incident |
| **Tools** | `ChromaDB` — vector similarity search; `SQLAlchemy DB` — reads `PolicyClauseEmbedding`; `LLMService` — coverage confirmation call |
| **Source** | `backend/services/rag_service.py`, `backend/rag/chroma_store.py` |

---

### 4. Customer Profile Agent

| Field | Detail |
|---|---|
| **Name** | Customer Profile Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Evaluates the claimant's risk profile using claim history, payment record, and account tenure |
| **Backstory** | A first-time claimant with perfect payment history is a very different risk than one with three prior escalated claims and missed premiums. This agent scores the customer so that the Decision Engine can weigh individual risk alongside the incident facts. |
| **Goal** | Return `customer_risk_score`, `prior_claims_count`, `signals[]` |
| **LLM** | None |
| **Tools** | `SQLAlchemy DB` — queries `Customer`, `Claim`, `PremiumPayment`, `CustomerProfile` tables |
| **Source** | `backend/services/customer_profile.py` |

---

### 5. Evidence Analysis Agent

| Field | Detail |
|---|---|
| **Name** | Evidence Analysis Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Validates every uploaded motor-claim document — damage photos, repair estimates, driver's licences, RC books, police FIRs, towing invoices — for authenticity and correctness of type |
| **Backstory** | Fraudulent claims often hinge on mismatched or fabricated documents. This agent runs OCR on each upload, pattern-matches it against expected content for the declared document type, and escalates to the LLM for a tie-break whenever rule-based matching is inconclusive. |
| **Goal** | Return `evidence_confidence_score`, `evidence_missing`, `evidence_results[]` (per-doc confidence + issues), `duplicate_uploads[]`, `evidence_mismatch`, `evidence_issues[]` |
| **LLM** | Groq (`llama-3`) via `LLMService.validate_evidence_document()` — used only when OCR pattern-match is inconclusive |
| **Tools** | `OCR Service` — text extraction from uploaded files; `LLMService` — tie-break document type validation; `SQLAlchemy DB` — reads `ClaimDocument` records |
| **Source** | `backend/services/evidence_analysis.py` |

---

### 6. Fraud Detection Agent

| Field | Detail |
|---|---|
| **Name** | Fraud Detection Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Motor-specific fraud rule engine combined with an LLM risk assessment |
| **Backstory** | Motor insurance is one of the most fraud-prone lines. Staged accidents, VIN mismatches, exaggerated repair estimates, and shared submission devices are common red flags. This agent runs a weighted signal model then sends a summary to the LLM for an independent risk score that is averaged with the rule-based score. |
| **Goal** | Return `fraud_score` (0–1), `signals[]`, `blacklist_hit`; persist a `FraudAssessment` record |
| **LLM** | Groq (`llama-3`) via `LLMService.analyze_fraud_risk()` |
| **Tools** | `SQLAlchemy DB` — queries `Customer` (blacklist), `Claim` (duplicates, frequency), `Policy` (coverage limit), device hash cross-customer lookup; `LLMService` — LLM fraud scoring |
| **Signal Weights** | duplicate_claim (0.30), abnormal_amount (0.25), blacklist (0.35), duplicate_document (0.15), policy_abuse (0.20), vin_mismatch (0.35), idv_ratio_aged_vehicle (0.20), third_party_no_police_report (0.20), device_hash_reuse (0.30), unlicensed_driver (0.30) |
| **Source** | `backend/services/fraud_detection.py` |

---

### 7. Escalation Evaluator Agent

| Field | Detail |
|---|---|
| **Name** | Escalation Evaluator Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Evaluates merged analysis results for motor-specific escalation conditions that require a human expert to review before a decision is issued |
| **Backstory** | Some claims are technically processable by the automated pipeline but still need a human eye — a total-loss suspected vehicle, a VIN that doesn't match the policy, third-party injuries, or a large claim without a police report. This agent applies a motor-domain flag set and produces customer-readable escalation messages. |
| **Goal** | Return `flags[]` and `messages[]`; update `claim.escalation_flags` and `claim.escalation_messages` in the database |
| **LLM** | Groq (`llama-3`) via `LLMService.check_clause_alignment()` — checks if the RAG-retrieved clause aligns with the policy schedule |
| **Tools** | `LLMService` — clause alignment check; `SQLAlchemy DB` — reads claim + policy data |
| **Motor Flags** | `high_fraud_score`, `low_evidence_confidence`, `evidence_mismatch`, `extraction_failed`, `early_claim_high_amount`, `clause_mismatch`, `total_loss_suspected`, `vin_mismatch`, `unlicensed_driver`, `third_party_injury_reported`, `no_police_report_major_loss` |
| **Source** | `backend/services/escalation_service.py` |

---

### 8. Decision Engine Agent

| Field | Detail |
|---|---|
| **Name** | Decision Engine Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Pure rules-based final adjudicator — maps all upstream scores and flags to a `ClaimStatus` and triggers human review when needed |
| **Backstory** | Every upstream agent produces a score or flag, but someone has to make the call. The Decision Engine applies a strict priority-ordered rule set — hard rejects first (expired policy, exclusion), then escalations and fraud thresholds, then low-confidence triggers — to arrive at a deterministic and auditable decision without any LLM non-determinism in the final outcome. |
| **Goal** | Return `ClaimStatus` (REJECTED / REQUEST_MORE_INFO / PENDING_REVIEW / ANALYSIS_COMPLETE / APPROVED), `reasoning`, `human_review_required` |
| **LLM** | None |
| **Tools** | Accepts `DecisionInput` dataclass (all upstream scores); updates `Claim` record via `ExplainabilityService.persist_decision()` |
| **Decision Rules (priority order)** | Policy expired → Reject · Premium unpaid → Reject · Incident excluded → Reject · Evidence missing → Request More Info · Escalation flags present → Pending Review · Fraud score ≥ threshold → Pending Review · Evidence confidence low → Pending Review · Claim amount > threshold → Pending Review · Confidence score low → Pending Review · Otherwise → Analysis Complete |
| **Source** | `backend/services/decision_engine.py` |

---

### 9. Payout Calculation Agent

| Field | Detail |
|---|---|
| **Name** | Payout Calculation Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Calculates the motor claim settlement amount using both a rules-based actuarial model and an LLM-derived parameter extraction |
| **Backstory** | Motor payouts are not simple arithmetic — they involve deductibles, age-based depreciation tables, co-pay percentages, total-loss detection against IDV, GST, own-damage vs third-party splits, and next-cycle NCB impact. The rules engine handles total-loss cases (> 75% IDV) directly; partial-loss claims are sent to the LLM to extract policy-specific parameters before the final calculation. |
| **Goal** | Return `payable_amount` and a detailed `breakdown` dict with gross amount, deductible, depreciation, co-pay, coverage cap, OD/TP split, GST, salvage, and NCB impact |
| **LLM** | Groq (`llama-3`) via `LLMService.extract_payout_parameters()` — extracts deductible, co-pay, depreciation rate, and formula steps from policy context |
| **Tools** | `PayoutCalculationService` (rules-based); `LLMPayoutService` (LLM-derived); `SQLAlchemy DB` — reads `Policy`, `Claim` |
| **Source** | `backend/services/payout_calculation.py`, `backend/services/llm_payout_service.py` |

---

### 10. LLM Reasoning Agent

| Field | Detail |
|---|---|
| **Name** | LLM Reasoning Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Central Groq LLM wrapper that provides all structured inference tasks across the platform |
| **Backstory** | Rather than each service invoking the LLM independently with no shared logic, all LLM calls are routed through a single service that handles key validation, retries, JSON extraction, and token budgeting. The agent surfaces specialist reasoning about motor policy coverage, fraud risk, payout parameters, policy document parsing, evidence validation, clause alignment, and decision explanations. |
| **Goal** | Provide structured JSON or natural-language outputs for: coverage assessment, fraud risk scoring, payout parameter extraction, policy document parsing, evidence document validation, clause alignment checking, and decision reasoning generation |
| **LLM** | Groq (`llama-3`, configurable via `settings.groq_model`); temperature 0 for structured outputs, 0.15 for assistant replies |
| **Tools** | `Groq API` via `langchain_groq.ChatGroq` |
| **Key Methods** | `analyze_incident_coverage()` · `analyze_fraud_risk()` · `generate_decision_reasoning()` · `analyze_policy_documents()` · `extract_policy_profile()` · `validate_evidence_document()` · `check_clause_alignment()` · `extract_payout_parameters()` |
| **Source** | `backend/services/llm_service.py` |

---

### 11. Explainability Agent

| Field | Detail |
|---|---|
| **Name** | Explainability Agent |
| **Type** | 🔵 Tool-calling Agent |
| **Role** | Computes a composite confidence score from all upstream signal scores and persists a full audit-grade decision record |
| **Backstory** | Regulators require that every automated insurance decision be explainable and auditable. This agent combines policy match quality, evidence confidence, customer risk, and clause clarity into a single weighted confidence score, then writes the full decision to the `ClaimDecision` and `AuditLog` tables to support regulator-ready compliance reporting. |
| **Goal** | Return `confidence_score`, `reasoning`, `retrieved_clauses[]`, `evidence_results[]`, `fraud_score`; persist `ClaimDecision` and `AuditLog` records |
| **LLM** | None (score computation is purely arithmetic); uses `LLMService.generate_decision_reasoning()` output passed in by the pipeline |
| **Tools** | `SQLAlchemy DB` — writes `ClaimDecision`, `AuditLog` |
| **Weights** | policy_match (0.30) · evidence (0.30) · customer_risk (0.20) · clause_clarity (0.20) |
| **Source** | `backend/services/explainability.py` |

---

### 12. Customer Copilot Assistant

| Field | Detail |
|---|---|
| **Name** | Customer Copilot Assistant |
| **Type** | 🟢 Conversational Agent |
| **Role** | Floating chat assistant for motor claim customers — answers questions about coverage, document requirements, approval odds, payout estimates, and next steps |
| **Backstory** | Insurance claim processes are opaque to customers. The Copilot bridges that gap by detecting what the customer is really asking (next step? status? documents? coverage?), pulling live claim analysis data, and producing a concise structured reply in plain English — no legalese, max 120 words. |
| **Goal** | Answer the customer's question using their real-time claim data; persist the conversation to memory; provide intent-specific replies (template for status/docs/next-step, LLM for coverage/general) |
| **LLM** | Groq (`llama-3`) via `LLMService.invoke_assistant()`; temperature 0 for structured, 0.15 for general |
| **Tools** | `SQLAlchemy DB` — reads `Claim`, `Policy`, `ClaimDecision`, `ClaimDocument`; `RAG Service` — retrieves policy clauses for coverage questions; `AssistantMemoryService` — persistent per-customer thread storage |
| **Intents Handled** | `NEXT_STEP`, `STATUS`, `DOCUMENTS`, `COVERAGE`, `GENERAL` |
| **Reply Constraints** | Max 120 words; structured format: `**In short:**` / `**What this means for you:**` / `**Do this next:**` |
| **Source** | `backend/services/universal_assistant_service.py`, `backend/services/assistant_response_service.py`, `backend/services/claim_assistant_service.py` |

---

### 13. Expert Copilot Assistant

| Field | Detail |
|---|---|
| **Name** | Expert Copilot Assistant |
| **Type** | 🟢 Conversational Agent |
| **Role** | Internal AI copilot for policy agents (experts) reviewing assigned motor claims — answers policy, claim, document, and customer questions with the full internal context visible only to experts |
| **Backstory** | Expert agents need to consult on complex claims quickly — what exactly does this policy cover? Is this evidence mismatch a real flag? What's the customer's risk profile? The Expert Copilot has access to internal claim analysis, OCR-extracted document text, customer KYC, and AI scores that customer-facing views never expose. |
| **Goal** | Deliver a concise structured answer (70–110 words) scoped to the expert's detected focus area (policy / claim / documents / customer / general); persist conversation to per-agent memory |
| **LLM** | Groq (`llama-3`) via `LLMService.invoke_assistant()`; temperature 0.15 |
| **Tools** | `SQLAlchemy DB` — reads `Claim`, `Policy`, `ClaimDocument`, `Customer`, `CustomerProfile`, `ClaimDecision`; `AssistantMemoryService` — persistent per-agent thread storage; `CustomerProfileService` — live risk scoring |
| **Focus Detection** | Keyword-scored intent classification: `policy`, `claim`, `documents`, `customer`, `general` |
| **Reply Constraints** | Max 110 words; structured format: `**Summary:**` / `**Key findings:**` / `**Recommended action:**` |
| **Source** | `backend/services/agent_assistant_service.py`, `backend/services/assistant_response_service.py` |

---

### 14. LangGraph Claim Workflow (Legacy)

| Field | Detail |
|---|---|
| **Name** | LangGraph Claim Workflow |
| **Type** | 🟣 Manager Agent (legacy graph-based) |
| **Role** | Original sequential LangGraph-based claim processing pipeline — now superseded by the parallel `claim_pipeline.py` but retained for reference |
| **Backstory** | The first implementation of the claim processing pipeline used LangGraph's `StateGraph` to define a strict sequential workflow: look up the policy → check coverage → validate the incident → detect fraud → make the final decision. While clear and auditable, the linear design meant each step waited for the previous, which the newer parallel orchestrator resolved. |
| **Goal** | Process a motor claim through five sequential nodes and arrive at a `final_decision` of Approve / Reject / Escalate |
| **LLM** | OpenAI `gpt-4o` (temperature 0) via `langchain_openai.ChatOpenAI` |
| **Tools** | `ChromaDB` — policy clause retrieval (`query_policy()`); `SQLAlchemy DB` — reads `Policy`, writes `Claim.status`, `Claim.fraud_flag`, `Claim.agent_reasoning` |
| **Graph Nodes (in order)** | `policy_lookup` → `coverage_check` → `incident_validation` → `fraud_check` → `eligibility_decision` |
| **Source** | `backend/agents/workflow.py`, `backend/agents/state.py` |

---

## Agent Interaction Flow

```
Customer submits Motor Claim
           │
           ▼
┌─────────────────────────────────┐
│  Claim Orchestrator (CrewAI)    │  (Manager — Flow[ClaimFlowState])
│  backend/crew/flow.py           │  @start → 4×@listen → @listen(and_)
└───────────────┬─────────────────┘
                │  fans out in parallel via @listen(claim_received)
    ┌───────┼────────────────────────┐
    │       │                        │                     │
    ▼       ▼                        ▼                     ▼
┌──────┐ ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
│Policy│ │ RAG Retrieval│  │ Customer Profile │  │Evidence Analysis │
│Valid.│ │    Agent     │  │     Agent        │  │     Agent        │
│Agent │ │(ChromaDB+LLM)│  │  (DB queries)    │  │  (OCR + LLM)     │
└──┬───┘ └──────┬───────┘  └────────┬─────────┘  └────────┬─────────┘
   │            │                   │                      │
   └────────────┴───────────────────┴──────────────────────┘
                            │
                            │  results merged
                            ▼
                ┌───────────────────────┐
                │ Fraud Detection Agent │  (rules + Groq LLM)
                └───────────┬───────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │ Escalation Evaluator  │  (motor flags + clause alignment LLM)
                └───────────┬───────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │ Explainability Agent  │  (confidence score computation)
                └───────────┬───────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │  Decision Engine      │  (pure rules, no LLM)
                └───────────┬───────────┘
                            │
                    ┌───────┴───────┐
                    │               │
                    ▼               ▼
         APPROVED/REJECTED    PENDING_REVIEW
                    │               │
                    ▼               ▼
        ┌──────────────────┐  ┌──────────────────┐
        │ Payout Calc Agent│  │  Human Expert    │
        │(rules + LLM)     │  │  (assigned by    │
        └──────────┬───────┘  │  expert_queue)   │
                   │          └──────────────────┘
                   ▼
        ┌──────────────────┐
        │ LLM Reasoning    │  (Groq — generates decision explanation)
        │    Agent         │
        └──────────┬───────┘
                   │
                   ▼
        ┌──────────────────┐
        │  Notification    │  customer notified
        │    Service       │
        └──────────────────┘


─────────────────── Conversational Layer (always on) ────────────────────

Customer ◄────► Customer Copilot Assistant  (Groq + RAG + Memory)
Expert   ◄────► Expert Copilot Assistant   (Groq + DB context + Memory)
```

---

## Data Flow Diagram

```
                              ┌─────────────────────────────────────────┐
                              │            CLAIM SUBMISSION              │
                              │  (incident, vehicle, amount, documents)  │
                              └────────────────────┬────────────────────┘
                                                   │
                                    ┌──────────────▼──────────────┐
                                    │      Claim Orchestrator      │
                                    │    (claim_pipeline.py)       │
                                    └──────────────┬──────────────┘
                                                   │
                     ┌──────────────┬──────────────┼──────────────┐
                     │              │              │              │
              ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼──────┐
              │  Policy    │ │   RAG      │ │ Customer   │ │ Evidence   │
              │ Validator  │ │ Retrieval  │ │ Profile    │ │ Analysis   │
              │            │ │            │ │            │ │            │
              │ DB: Policy │ │ ChromaDB   │ │ DB: Claims │ │ OCR +      │
              │ PremiumPay │ │ LLM(Groq)  │ │ Customer   │ │ LLM(Groq)  │
              └──────┬─────┘ └──────┬─────┘ └──────┬─────┘ └──────┬──────┘
                     │              │              │              │
                     └──────────────┴──────────────┴──────────────┘
                                                   │ merged results
                                    ┌──────────────▼──────────────┐
                                    │     Fraud Detection Agent    │
                                    │  (rules: 10 signals         │
                                    │   + Groq LLM fraud score)   │
                                    └──────────────┬──────────────┘
                                                   │
                                    ┌──────────────▼──────────────┐
                                    │   Escalation Evaluator       │
                                    │  (11 motor flags             │
                                    │   + Groq clause alignment)  │
                                    └──────────────┬──────────────┘
                                                   │
                                    ┌──────────────▼──────────────┐
                                    │    Explainability Agent      │
                                    │  (confidence = weighted avg  │
                                    │   of 4 upstream scores)      │
                                    │   writes: ClaimDecision      │
                                    │           AuditLog           │
                                    └──────────────┬──────────────┘
                                                   │
                                    ┌──────────────▼──────────────┐
                                    │      Decision Engine         │
                                    │  (priority-ordered rules)    │
                                    │  → REJECTED                  │
                                    │  → REQUEST_MORE_INFO         │
                                    │  → PENDING_REVIEW ──────────►│ HumanReview
                                    │  → ANALYSIS_COMPLETE         │ (DB record)
                                    │  → APPROVED                  │
                                    └──────────────┬──────────────┘
                                                   │ if APPROVED
                                    ┌──────────────▼──────────────┐
                                    │   Payout Calculation Agent   │
                                    │  rules path: total-loss IDV  │
                                    │  LLM path : Groq params +    │
                                    │  deduct/deprec/copay/GST     │
                                    └──────────────┬──────────────┘
                                                   │
                                    ┌──────────────▼──────────────┐
                                    │     LLM Reasoning Agent      │
                                    │  (Groq — 3-5 sentence        │
                                    │   regulator-ready decision   │
                                    │   explanation)               │
                                    └──────────────┬──────────────┘
                                                   │
                                    ┌──────────────▼──────────────┐
                                    │      Notification Service    │
                                    │  → Customer notified         │
                                    │  → Expert assigned if needed │
                                    └─────────────────────────────┘


─────────── Parallel Conversational Layer (stateful, multi-thread) ───────────

  CUSTOMER ◄──────► Customer Copilot         EXPERT ◄──────► Expert Copilot
              │      (UniversalAssistant)              │      (AgentAssistant)
              │      Groq LLM                          │      Groq LLM
              │      RAG (ChromaDB)                    │      DB Context
              │      AssistantMemory (PostgreSQL)      │      AssistantMemory
              └──────────────────────────────────────────────────────────────┘

─────────────── Legacy Sequential Path (LangGraph — agents/workflow.py) ──────
  policy_lookup → coverage_check → incident_validation → fraud_check
  → eligibility_decision   [uses GPT-4o; superseded by the parallel pipeline]
```

---

## How to Enable the CrewAI Flow

The Flow is feature-flagged and defaults to **off** so the legacy pipeline
remains the production path for one release.

```bash
# In backend/.env — flip on:
USE_CREWAI_FLOW=true
```

- **Sync path** (SQLite / dev): `services.orchestrator.ClaimOrchestrator._run_sync` reads `settings.use_crewai_flow` and routes to `crew.flow.run_claim_flow` instead of `services.claim_pipeline.run_claim_pipeline`.
- **Celery path** (Postgres / prod): `tasks.claim_tasks.orchestrate_claim_task` short-circuits into `run_claim_flow` when the flag is on; otherwise the existing `chord(group(...), generate_decision_task.s(...))` runs.
- **Fallback safety**: if `crewai` is not installed at runtime, `run_claim_flow` transparently falls back to a `ThreadPoolExecutor` equivalent — the flag can be enabled without adding the dep in an emergency rollout.

Dependency: `crewai>=0.80.0` is now declared in `backend/pyproject.toml`.

## Notes

- **Parallelism**: The Claim Orchestrator runs `Policy Validator`, `RAG Retrieval`, `Customer Profile`, and `Evidence Analysis` agents concurrently using Python's `ThreadPoolExecutor(max_workers=4)`. Fraud detection runs sequentially after evidence (it needs evidence results as input).

- **LLM Usage Pattern**: LLM calls are concentrated in four agents — RAG Retrieval (coverage confirmation), Evidence Analysis (tie-break validation), Fraud Detection (independent fraud score), and LLM Reasoning (decision explanation). The Decision Engine is intentionally LLM-free for determinism and auditability.

- **Total-Loss Fast Path**: When a motor claim's repair cost exceeds 75% of the vehicle's IDV, the Payout Agent bypasses the LLM path and applies the rules-based total-loss formula (IDV − 10% salvage) to avoid LLM re-derivation on a settled calculation.

- **Memory Architecture**: Both conversational assistants use a `AssistantMemory` model (PostgreSQL-backed) with per-user sessions, per-claim threads, and automatic compaction when a thread exceeds 20 messages.

- **Audit Trail**: Every stage emits events to `progress_service` (real-time SSE to the frontend) and writes structured records to the `AuditLog` table for regulator-ready compliance reporting.
