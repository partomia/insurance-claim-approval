# Assistant memory — STM + LTM

The assistant memory layer is the single source of truth for every copilot
conversation (customer + expert). It replaces three flat legacy chat tables
(`claim_chat_messages`, `customer_chat_messages`, `agent_chat_messages`) with a
three-tier model that supports threads, running summaries, and per-persona
long-term facts.

## Data model

```
AssistantSession           (per owner + persona; holds LTM)
    ├── AssistantThread    (a conversation; general or per-claim)
    │       └── AssistantMessage  (user | assistant turn)
    └── long_term_memory_json  (durable persona facts)
```

**Session** — one per `(owner_type, owner_id, persona)` triple.
- `owner_type`: `customer` or `agent`
- `persona`: `customer_copilot` or `expert_copilot`
- Enforced by `uq_assistant_session_owner_persona`.

**Thread** — a conversation container.
- `thread_type`: `general` (default chat) or `claim` (per-claim thread).
- `claim_id` (nullable): links a `claim` thread to `claims.id` with
  `ondelete=SET NULL` — deleting a claim preserves the transcript.
- `summary_text` (nullable): running compacted summary of older turns.
- `message_count`, `last_compacted_at`: bookkeeping for compaction.
- Unique on `(session_id, thread_type, claim_id)` — one claim thread per session.

**Message** — one turn.
- `role`: `USER` or `ASSISTANT`.
- `context_json`: audit payload (page route, claim_id, policy_number, etc.);
  duplicated on both user and assistant rows so audits don't need a self-join.
- Composite index `ix_assistant_messages_thread_created` on
  `(thread_id, created_at)` covers every hot query.

## Short-term memory (STM) — per thread

Verbatim recent turns kept in the prompt every time.

- Turn cap: `ASSISTANT_RECENT_TURN_LIMIT` (default 8).
- Loaded by `load_context_window(db, thread)` → `(summary_text, [messages])`.
- `summary_text` is empty until the thread crosses both compaction thresholds.

## Compaction — folding old turns into a summary + facts

`maybe_compact_thread(db, thread, session)` runs after every persist. It compacts
only when **both** thresholds are exceeded, and only folds *new* older turns
(anything with `created_at > thread.last_compacted_at`).

Triggers:
1. `thread.message_count > ASSISTANT_COMPACTION_MESSAGE_THRESHOLD` (default 16), **and**
2. Total chars (summary + all messages) > `ASSISTANT_COMPACTION_CHAR_THRESHOLD` (default 6000).

When triggered, a **single** LLM call (`_compact_older_text`) returns

```json
{
  "summary": "concise third-person recap (max 200 words)",
  "facts":   [{"key": "…", "fact": "…"}, ...]
}
```

- `summary` replaces `thread.summary_text` (hard-capped at
  `ASSISTANT_SUMMARY_CHAR_CAP` chars, default 1500).
- `facts` are merged into the session LTM (see below).
- `thread.last_compacted_at` is updated so the next compaction only sees new
  older turns — bounds LLM cost at O(N) instead of O(N²).

On parse failure, the raw response is used as a plain summary; fact extraction
is silently skipped.

## Long-term memory (LTM) — per persona

Durable facts about the user/expert stored on `AssistantSession.long_term_memory_json`.

Record shape:

```json
{
  "key":        "prefers-hindi",
  "fact":       "prefers Hindi replies",
  "first_seen": "2026-07-26T12:34:56",
  "last_seen":  "2026-07-26T18:00:01",
  "hits":       3
}
```

- **Slug normalization** — keys are lowercased, non-alphanumerics collapsed to `-`,
  truncated to 64 chars. Fallback key is `sha1(fact)[:8]`. Prevents empty-key
  collisions from wiping facts.
- **Hit counting** — every re-mention bumps `hits` and refreshes `last_seen`;
  the newest phrasing of the fact is kept.
- **Eviction** — when merged size > `ASSISTANT_MAX_LONG_TERM_FACTS` (default 20),
  the lowest-`hits` / oldest-`last_seen` facts are dropped first.
- **Backward compat** — legacy `{key, fact}`-only records are upgraded on read
  (`load_long_term_memory`) with synthesized timestamps.

LTM is rendered into every prompt as `"LONG-TERM MEMORY (persona facts):\n- …"`.

## Prompt shape

Both copilots build prompts in the same order:

```
[LTM block]           — omitted if empty
[ACCOUNT / CLAIM ctx] — always present
[RAG excerpts]        — customer copilot only, when intent is coverage/general
[THREAD SUMMARY]      — omitted if empty
CONVERSATION HISTORY: — last N recent messages (verbatim)
USER: <current message>
```

Empty blocks are skipped so short threads don't waste tokens.

## Backfill (legacy → v2)

`backfill_legacy_messages(db)` in `assistant_memory_service.py` migrates the
three legacy chat tables into the new model. It is:

- **Idempotent** — per-row `(thread_id, role, created_at)` skip. Role is part of
  the key so a user+assistant turn saved at the same microsecond both survive.
- **Incremental** — re-runs pick up any new legacy rows added between boots.
- **Fail-safe** — a partial migration rolls back and the next boot retries.

Called from `db_init.py:_backfill_assistant_threads`, gated by
`ASSISTANT_BACKFILL_ON_STARTUP` (default `true`). Flip to `false` in production
after the first successful boot so restarts don't table-scan legacy chat tables.

## Observability

Every compaction emits one structured log line:

```
assistant_compaction thread=42 persona=customer_copilot new_msgs=12
  in_chars=6421 summary_chars=812 facts=3 elapsed_ms=1104
```

Ship these to your log aggregator to spot cost hot spots.

## Public API — what to call from a service

```python
from services.assistant_memory_service import assistant_memory_service
from models.assistant_memory import AssistantOwnerType, AssistantPersona

session = assistant_memory_service.get_or_create_session(
    db,
    owner_type=AssistantOwnerType.CUSTOMER,
    owner_id=customer.id,
    persona=AssistantPersona.CUSTOMER_COPILOT,
)
thread = assistant_memory_service.resolve_thread(
    db, session, thread_id=body.thread_id, claim_id=body.claim_id
)

summary, recent = assistant_memory_service.load_context_window(db, thread)
ltm            = assistant_memory_service.format_long_term_memory(session)

# … build prompt, call LLM, get reply …

assistant_memory_service.persist_exchange(
    db, thread, user_message, reply, context_json={...}
)
assistant_memory_service.maybe_compact_thread(db, thread, session)
```

## Tunables

Every knob is env-configurable under the `ASSISTANT_*` namespace — see
[`env-reference.md`](./env-reference.md).

## Regression tests

`backend/tests/test_assistant_memory.py` covers:

- **B1** — `universal_assistant_service.get_history` accepts `Customer` (not int).
- **B2** — `claim_assistant_service.get_history` accepts `(claim_id, customer_id)`.
- **B3** — `llm_service.validate_evidence_document` returns `None` without key.
- **B4** — Compaction does not re-summarize on turns with no new older material.
- **B5** — Backfill is idempotent and picks up new legacy rows.
- **M1** — Default general thread is the oldest one (stable primary).
- **M2** — LTM upgrades legacy shape, slug-dedupes, evicts by hits+recency.
- **M4** — Compaction makes exactly one combined LLM call.
- **M6** — Backfill keeps user+assistant rows sharing a timestamp.
