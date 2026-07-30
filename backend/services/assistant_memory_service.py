"""Assistant sessions, threads, short-term (STM) and long-term (LTM) memory.

- STM lives on `AssistantThread`: recent turns + a running `summary_text`.
- LTM lives on `AssistantSession.long_term_memory_json`: durable persona facts
  carried across every thread for that (owner, persona).

Tuning knobs read from `config.Settings` so operators can dial cost vs. context
depth per environment (see .env.example: `ASSISTANT_*`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import get_settings
from models.assistant_memory import (
    AssistantMessage,
    AssistantOwnerType,
    AssistantPersona,
    AssistantSession,
    AssistantThread,
    AssistantThreadType,
)
from models.chat import AgentChatMessage, ChatRole, ClaimChatMessage, CustomerChatMessage
from services.llm_service import llm_service

logger = logging.getLogger(__name__)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    """Normalize a key to a stable slug for de-duplication."""
    cleaned = _SLUG_STRIP.sub("-", (value or "").lower()).strip("-")
    return cleaned[:64]


def _content_hash(text: str) -> str:
    """8-char SHA1 prefix — fallback LTM key when no explicit key is given."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:8]


class AssistantMemoryService:
    # --- Session (per owner + persona) ---------------------------------

    def get_or_create_session(
        self,
        db: Session,
        *,
        owner_type: AssistantOwnerType,
        owner_id: int,
        persona: AssistantPersona,
    ) -> AssistantSession:
        session = (
            db.query(AssistantSession)
            .filter(
                AssistantSession.owner_type == owner_type,
                AssistantSession.owner_id == owner_id,
                AssistantSession.persona == persona,
            )
            .first()
        )
        if session:
            return session

        session = AssistantSession(
            owner_type=owner_type,
            owner_id=owner_id,
            persona=persona,
            long_term_memory_json="[]",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    # --- Threads --------------------------------------------------------

    def list_threads(self, db: Session, session: AssistantSession) -> list[AssistantThread]:
        return (
            db.query(AssistantThread)
            .filter(AssistantThread.session_id == session.id)
            .order_by(AssistantThread.updated_at.desc())
            .all()
        )

    def get_thread(
        self,
        db: Session,
        session: AssistantSession,
        thread_id: int,
    ) -> AssistantThread | None:
        return (
            db.query(AssistantThread)
            .filter(
                AssistantThread.id == thread_id,
                AssistantThread.session_id == session.id,
            )
            .first()
        )

    def create_general_thread(
        self,
        db: Session,
        session: AssistantSession,
        *,
        title: str | None = None,
    ) -> AssistantThread:
        thread = AssistantThread(
            session_id=session.id,
            thread_type=AssistantThreadType.GENERAL,
            title=title or "General chat",
        )
        db.add(thread)
        db.commit()
        db.refresh(thread)
        return thread

    def get_or_create_claim_thread(
        self,
        db: Session,
        session: AssistantSession,
        claim_id: int,
        *,
        title: str | None = None,
    ) -> AssistantThread:
        thread = (
            db.query(AssistantThread)
            .filter(
                AssistantThread.session_id == session.id,
                AssistantThread.thread_type == AssistantThreadType.CLAIM,
                AssistantThread.claim_id == claim_id,
            )
            .first()
        )
        if thread:
            return thread

        thread = AssistantThread(
            session_id=session.id,
            thread_type=AssistantThreadType.CLAIM,
            claim_id=claim_id,
            title=title or f"Claim #{claim_id}",
        )
        db.add(thread)
        db.commit()
        db.refresh(thread)
        return thread

    def resolve_thread(
        self,
        db: Session,
        session: AssistantSession,
        *,
        thread_id: Optional[int] = None,
        claim_id: Optional[int] = None,
    ) -> AssistantThread:
        if claim_id is not None:
            return self.get_or_create_claim_thread(db, session, claim_id)

        if thread_id is not None:
            thread = self.get_thread(db, session, thread_id)
            if not thread:
                raise ValueError("Thread not found")
            return thread

        # M1: pick the *oldest* general thread as the stable primary. Ordering
        # by `updated_at DESC` used to make the "default" chat silently switch
        # every time a different thread was touched.
        thread = (
            db.query(AssistantThread)
            .filter(
                AssistantThread.session_id == session.id,
                AssistantThread.thread_type == AssistantThreadType.GENERAL,
            )
            .order_by(AssistantThread.created_at.asc())
            .first()
        )
        if thread:
            return thread
        return self.create_general_thread(db, session)

    # --- STM (per-thread short-term memory) -----------------------------

    def get_thread_history(
        self,
        db: Session,
        thread: AssistantThread,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if limit is None:
            limit = get_settings().assistant_history_limit
        messages = (
            db.query(AssistantMessage)
            .filter(AssistantMessage.thread_id == thread.id)
            .order_by(AssistantMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        messages.reverse()
        return [
            {
                "role": m.role.value,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]

    def load_context_window(
        self,
        db: Session,
        thread: AssistantThread,
    ) -> tuple[str, list[AssistantMessage]]:
        limit = get_settings().assistant_recent_turn_limit
        recent = (
            db.query(AssistantMessage)
            .filter(AssistantMessage.thread_id == thread.id)
            .order_by(AssistantMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        recent.reverse()
        # M5: never surface an empty summary — callers can skip emitting the
        # "THREAD SUMMARY:" block on prompts entirely.
        summary = (thread.summary_text or "").strip()
        return summary, recent

    def format_history_text(self, messages: list[AssistantMessage]) -> str:
        if not messages:
            return "No prior messages."
        return "\n".join(f"{m.role.value}: {m.content}" for m in messages)

    def estimate_context_chars(
        self,
        *,
        summary_text: str,
        messages: list[AssistantMessage],
        extra: str = "",
    ) -> int:
        total = len(summary_text) + len(extra)
        for msg in messages:
            total += len(msg.content)
        return total

    # --- LTM (per-persona long-term memory) -----------------------------

    def load_long_term_memory(self, session: AssistantSession) -> list[dict[str, Any]]:
        """Return LTM facts, upgrading any legacy `{key, fact}`-only entries in place."""
        try:
            raw = json.loads(session.long_term_memory_json or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []

        now = datetime.utcnow().isoformat()
        upgraded: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("fact"):
                continue
            fact = str(item["fact"]).strip()
            key = _slug(str(item.get("key") or "")) or _content_hash(fact)
            upgraded.append(
                {
                    "key": key,
                    "fact": fact,
                    "first_seen": item.get("first_seen") or now,
                    "last_seen": item.get("last_seen") or now,
                    "hits": int(item.get("hits") or 1),
                }
            )
        return upgraded

    def format_long_term_memory(self, session: AssistantSession) -> str:
        facts = self.load_long_term_memory(session)
        if not facts:
            return ""
        cap = get_settings().assistant_max_long_term_facts
        lines = [f"- {item['fact']}" for item in facts[:cap]]
        return "LONG-TERM MEMORY (persona facts):\n" + "\n".join(lines)

    def _merge_long_term_facts(
        self,
        db: Session,
        session: AssistantSession,
        new_facts: list[dict[str, str]],
    ) -> None:
        """M2/M3: durable, slug-keyed merge with hit-count eviction; self-committing."""
        if not new_facts:
            return

        settings = get_settings()
        now = datetime.utcnow().isoformat()

        existing = {item["key"]: item for item in self.load_long_term_memory(session)}

        for item in new_facts:
            fact = str(item.get("fact") or "").strip()
            if not fact:
                continue
            key = _slug(str(item.get("key") or "")) or _content_hash(fact)
            if key in existing:
                existing[key]["fact"] = fact  # keep newest phrasing
                existing[key]["last_seen"] = now
                existing[key]["hits"] = int(existing[key].get("hits", 1)) + 1
            else:
                existing[key] = {
                    "key": key,
                    "fact": fact,
                    "first_seen": now,
                    "last_seen": now,
                    "hits": 1,
                }

        # Evict least-useful facts first: lowest hits, then oldest last_seen.
        merged = sorted(
            existing.values(),
            key=lambda x: (-int(x.get("hits", 1)), x.get("last_seen") or ""),
        )[: settings.assistant_max_long_term_facts]

        session.long_term_memory_json = json.dumps(merged)
        session.updated_at = datetime.utcnow()
        db.commit()

    # --- Persistence + compaction --------------------------------------

    def persist_exchange(
        self,
        db: Session,
        thread: AssistantThread,
        user_message: str,
        reply: str,
        *,
        context_json: dict[str, Any] | None = None,
    ) -> None:
        context_blob = json.dumps(context_json) if context_json else None
        db.add(
            AssistantMessage(
                thread_id=thread.id,
                role=ChatRole.USER,
                content=user_message,
                context_json=context_blob,
            )
        )
        db.add(
            AssistantMessage(
                thread_id=thread.id,
                role=ChatRole.ASSISTANT,
                content=reply,
                # Duplicate audit context on the assistant row so we can trace
                # which page/claim produced any given reply without a self-join.
                context_json=context_blob,
            )
        )
        thread.message_count = (thread.message_count or 0) + 2
        thread.updated_at = datetime.utcnow()
        db.commit()

    def maybe_compact_thread(
        self,
        db: Session,
        thread: AssistantThread,
        session: AssistantSession,
    ) -> None:
        settings = get_settings()
        recent_limit = settings.assistant_recent_turn_limit

        all_messages = (
            db.query(AssistantMessage)
            .filter(AssistantMessage.thread_id == thread.id)
            .order_by(AssistantMessage.created_at.asc())
            .all()
        )
        if len(all_messages) <= recent_limit:
            return

        recent_ids = {m.id for m in all_messages[-recent_limit:]}
        older = [m for m in all_messages if m.id not in recent_ids]
        if not older:
            return

        # Only fold in messages that haven't been summarized yet. Without this
        # bound, every turn past the threshold re-summarizes the entire history
        # and blows up LLM cost O(N²).
        last_compacted = thread.last_compacted_at
        new_older = (
            [m for m in older if m.created_at > last_compacted]
            if last_compacted
            else older
        )
        if not new_older:
            return

        char_estimate = self.estimate_context_chars(
            summary_text=thread.summary_text or "",
            messages=all_messages,
        )
        if (
            thread.message_count <= settings.assistant_compaction_message_threshold
            and char_estimate <= settings.assistant_compaction_char_threshold
        ):
            return

        older_text = "\n".join(f"{m.role.value}: {m.content}" for m in new_older)

        # M4/M9: single combined LLM call for summary + fact extraction, timed.
        start_ms = time.monotonic()
        summary, facts = self._compact_older_text(
            session.persona,
            existing_summary=thread.summary_text or "",
            older_text=older_text,
        )
        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        if summary:
            cap = settings.assistant_summary_char_cap
            if len(summary) > cap:
                summary = summary[:cap].rstrip() + " …"
            thread.summary_text = summary
            thread.last_compacted_at = datetime.utcnow()

        if facts:
            self._merge_long_term_facts(db, session, facts)

        thread.updated_at = datetime.utcnow()
        db.commit()

        logger.info(
            "assistant_compaction thread=%s persona=%s new_msgs=%d in_chars=%d "
            "summary_chars=%d facts=%d elapsed_ms=%d",
            thread.id,
            session.persona.value,
            len(new_older),
            len(older_text),
            len(summary or ""),
            len(facts or []),
            elapsed_ms,
        )

    def _compact_older_text(
        self,
        persona: AssistantPersona,
        *,
        existing_summary: str,
        older_text: str,
    ) -> tuple[str, list[dict[str, str]]]:
        """Combined summarize + LTM fact extraction in one LLM call (M4).

        Falls back to summary-only if the JSON payload can't be parsed.
        Returns `(summary_text, facts_list)`.
        """
        settings = get_settings()
        persona_label = (
            "policyholder"
            if persona == AssistantPersona.CUSTOMER_COPILOT
            else "insurance expert"
        )
        system = (
            "You compress conversation history for an assistant and extract durable "
            f"facts about this {persona_label}. "
            "Return ONLY a JSON object with keys: "
            "`summary` (concise third-person recap, max 200 words, preserve open "
            "questions/decisions/claim refs/preferences, no markdown headers), "
            "`facts` (JSON array of {\"key\": string, \"fact\": string} for durable "
            "traits/preferences/recurring topics — exclude transient claim status; "
            "empty array if nothing durable)."
        )
        user = f"""Existing summary:
{existing_summary or 'None'}

Messages to fold in:
{older_text}

Return JSON only."""
        raw = llm_service.invoke_summarize(
            system, user, max_tokens=settings.assistant_summary_max_tokens
        )
        if not raw:
            return existing_summary, []

        summary, facts = self._parse_compact_payload(raw)
        if not summary and not facts:
            # Fallback: treat the raw text as a plain summary.
            return raw.strip(), []
        return (summary or existing_summary), facts

    @staticmethod
    def _parse_compact_payload(raw: str) -> tuple[str, list[dict[str, str]]]:
        """Best-effort parse of a `{summary, facts}` payload."""
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return "", []
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return "", []
        if not isinstance(parsed, dict):
            return "", []

        summary = str(parsed.get("summary") or "").strip()
        facts_raw = parsed.get("facts") or []
        facts: list[dict[str, str]] = []
        if isinstance(facts_raw, list):
            for item in facts_raw:
                if not isinstance(item, dict):
                    continue
                fact = str(item.get("fact") or "").strip()
                if not fact:
                    continue
                key = str(item.get("key") or "").strip()
                facts.append({"key": key, "fact": fact})
        return summary, facts

    # --- View helpers ---------------------------------------------------

    def thread_to_dict(self, thread: AssistantThread) -> dict[str, Any]:
        return {
            "id": thread.id,
            "thread_type": thread.thread_type.value,
            "claim_id": thread.claim_id,
            "title": thread.title,
            "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
        }


# --- Backfill helpers (legacy chat → assistant memory) -------------------


def _already_migrated(
    db: Session,
    thread: AssistantThread,
    role: ChatRole,
    created_at: datetime,
) -> bool:
    """M6: role is part of the natural key so a user/assistant pair sharing the
    same microsecond timestamp isn't collapsed to one row.
    """
    return (
        db.query(AssistantMessage.id)
        .filter(
            AssistantMessage.thread_id == thread.id,
            AssistantMessage.role == role,
            AssistantMessage.created_at == created_at,
        )
        .first()
        is not None
    )


def backfill_legacy_messages(db: Session) -> None:
    """Migrate legacy flat chat tables into assistant threads.

    Safe to re-run. Skips any legacy row already present, so a partial migration
    or newly-appended legacy rows are picked up on the next boot.
    """
    memory = AssistantMemoryService()

    try:
        _backfill_customer_messages(db, memory)
        _backfill_claim_messages(db, memory)
        _backfill_agent_messages(db, memory)
    except Exception:
        # Roll back partial writes so the next boot retries cleanly.
        db.rollback()
        logger.exception("Assistant backfill failed; rolling back partial migration")
        raise


def _backfill_customer_messages(db: Session, memory: "AssistantMemoryService") -> None:
    customer_sessions: dict[int, AssistantSession] = {}
    customer_general: dict[int, AssistantThread] = {}

    for msg in (
        db.query(CustomerChatMessage)
        .order_by(CustomerChatMessage.customer_id, CustomerChatMessage.created_at)
        .all()
    ):
        session = customer_sessions.get(msg.customer_id)
        if not session:
            session = memory.get_or_create_session(
                db,
                owner_type=AssistantOwnerType.CUSTOMER,
                owner_id=msg.customer_id,
                persona=AssistantPersona.CUSTOMER_COPILOT,
            )
            customer_sessions[msg.customer_id] = session
            customer_general[msg.customer_id] = _get_or_create_general_thread(
                db, memory, session
            )

        thread = customer_general[msg.customer_id]
        if _already_migrated(db, thread, msg.role, msg.created_at):
            continue
        db.add(
            AssistantMessage(
                thread_id=thread.id,
                role=msg.role,
                content=msg.content,
                context_json=msg.context_json,
                created_at=msg.created_at,
            )
        )
        thread.message_count = (thread.message_count or 0) + 1
    db.commit()


def _backfill_claim_messages(db: Session, memory: "AssistantMemoryService") -> None:
    from models.claim import Claim

    session_cache: dict[int, AssistantSession] = {}
    claim_threads: dict[tuple[int, int], AssistantThread] = {}

    for msg in (
        db.query(ClaimChatMessage)
        .order_by(ClaimChatMessage.claim_id, ClaimChatMessage.created_at)
        .all()
    ):
        claim = db.query(Claim).filter(Claim.id == msg.claim_id).first()
        if not claim:
            continue
        session = session_cache.get(claim.customer_id)
        if not session:
            session = memory.get_or_create_session(
                db,
                owner_type=AssistantOwnerType.CUSTOMER,
                owner_id=claim.customer_id,
                persona=AssistantPersona.CUSTOMER_COPILOT,
            )
            session_cache[claim.customer_id] = session

        key = (session.id, msg.claim_id)
        thread = claim_threads.get(key)
        if not thread:
            thread = memory.get_or_create_claim_thread(
                db, session, msg.claim_id, title=f"Claim #{msg.claim_id}"
            )
            claim_threads[key] = thread

        if _already_migrated(db, thread, msg.role, msg.created_at):
            continue
        db.add(
            AssistantMessage(
                thread_id=thread.id,
                role=msg.role,
                content=msg.content,
                created_at=msg.created_at,
            )
        )
        thread.message_count = (thread.message_count or 0) + 1
    db.commit()


def _backfill_agent_messages(db: Session, memory: "AssistantMemoryService") -> None:
    agent_sessions: dict[int, AssistantSession] = {}
    agent_general_threads: dict[int, AssistantThread] = {}
    agent_claim_threads: dict[tuple[int, int], AssistantThread] = {}

    for msg in (
        db.query(AgentChatMessage)
        .order_by(AgentChatMessage.agent_id, AgentChatMessage.created_at)
        .all()
    ):
        session = agent_sessions.get(msg.agent_id)
        if not session:
            session = memory.get_or_create_session(
                db,
                owner_type=AssistantOwnerType.AGENT,
                owner_id=msg.agent_id,
                persona=AssistantPersona.EXPERT_COPILOT,
            )
            agent_sessions[msg.agent_id] = session
            agent_general_threads[msg.agent_id] = _get_or_create_general_thread(
                db, memory, session
            )

        if msg.claim_id:
            key = (session.id, msg.claim_id)
            thread = agent_claim_threads.get(key)
            if not thread:
                thread = memory.get_or_create_claim_thread(
                    db, session, msg.claim_id, title=f"Claim #{msg.claim_id}"
                )
                agent_claim_threads[key] = thread
        else:
            thread = agent_general_threads[msg.agent_id]

        if _already_migrated(db, thread, msg.role, msg.created_at):
            continue
        db.add(
            AssistantMessage(
                thread_id=thread.id,
                role=msg.role,
                content=msg.content,
                context_json=msg.context_json,
                created_at=msg.created_at,
            )
        )
        thread.message_count = (thread.message_count or 0) + 1
    db.commit()


def _get_or_create_general_thread(
    db: Session,
    memory: "AssistantMemoryService",
    session: AssistantSession,
) -> AssistantThread:
    """Return the existing general thread for a session, or create one."""
    existing = (
        db.query(AssistantThread)
        .filter(
            AssistantThread.session_id == session.id,
            AssistantThread.thread_type == AssistantThreadType.GENERAL,
        )
        .order_by(AssistantThread.created_at.asc())
        .first()
    )
    if existing:
        return existing
    return memory.create_general_thread(db, session, title="General chat")


assistant_memory_service = AssistantMemoryService()
