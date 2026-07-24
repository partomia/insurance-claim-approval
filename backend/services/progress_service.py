import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import redis

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_memory_channels: dict[int, deque] = {}
_memory_lock = threading.Lock()


class ProgressService:
    STEPS = [
        "claim_submitted",
        "policy_validation",
        "rag_retrieval",
        "customer_profile",
        "evidence_analysis",
        "fraud_detection",
        "decision_engine",
        "payout_calculation",
        "completed",
        "pipeline_reset",
    ]

    STEP_LABELS = {
        "claim_submitted": "Claim received",
        "policy_validation": "Checking your policy",
        "rag_retrieval": "Reviewing policy terms",
        "customer_profile": "Verifying your details",
        "evidence_analysis": "Reviewing your documents",
        "fraud_detection": "Safety checks",
        "decision_engine": "Assessing your claim",
        "payout_calculation": "Calculating payout",
        "completed": "Review complete",
        "pipeline_reset": "Rechecking documents",
        "human_review": "Expert assigned",
    }

    def __init__(self) -> None:
        self._redis: Optional[redis.Redis] = None
        self._redis_disabled = False

    @property
    def redis_client(self) -> Optional[redis.Redis]:
        if self._redis_disabled:
            return None
        if self._redis is None:
            try:
                self._redis = redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.5,
                    socket_timeout=0.5,
                )
                self._redis.ping()
            except Exception as exc:
                logger.debug("Redis unavailable, using in-memory progress: %s", exc)
                self._redis = None
                self._redis_disabled = True
        return self._redis

    def _channel(self, claim_id: int) -> str:
        return f"claim:{claim_id}:events"

    def _history_key(self, claim_id: int) -> str:
        return f"claim:{claim_id}:history"

    def publish(
        self,
        claim_id: int,
        step: str,
        status: str,
        message: str,
        data: Optional[dict[str, Any]] = None,
        run_id: Optional[int] = None,
    ) -> dict[str, Any]:
        event = {
            "claim_id": claim_id,
            "step": step,
            "label": self.STEP_LABELS.get(step, step),
            "status": status,
            "message": message,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if run_id is not None:
            event["run_id"] = run_id
        payload = json.dumps(event)

        client = self.redis_client
        if client:
            try:
                client.publish(self._channel(claim_id), payload)
                client.rpush(self._history_key(claim_id), payload)
                client.expire(self._history_key(claim_id), 3600)
            except Exception as exc:
                logger.debug("Redis publish failed: %s", exc)

        with _memory_lock:
            if claim_id not in _memory_channels:
                _memory_channels[claim_id] = deque(maxlen=100)
            _memory_channels[claim_id].append(event)

        self._persist_event(event)
        return event

    def _persist_event(self, event: dict[str, Any]) -> None:
        try:
            from database import SessionLocal
            from models.claim_progress import ClaimProgressEvent

            db = SessionLocal()
            try:
                db.add(ClaimProgressEvent(claim_id=int(event["claim_id"]), payload=event))
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Progress DB persist failed: %s", exc)

    def get_history(self, claim_id: int) -> list[dict[str, Any]]:
        client = self.redis_client
        if client:
            try:
                raw = client.lrange(self._history_key(claim_id), 0, -1)
                if raw:
                    return [json.loads(item) for item in raw]
            except Exception:
                pass

        try:
            from database import SessionLocal
            from models.claim_progress import ClaimProgressEvent

            db = SessionLocal()
            try:
                rows = (
                    db.query(ClaimProgressEvent)
                    .filter(ClaimProgressEvent.claim_id == claim_id)
                    .order_by(ClaimProgressEvent.id.asc())
                    .limit(100)
                    .all()
                )
                if rows:
                    return [row.payload for row in rows]
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Progress DB read failed: %s", exc)

        with _memory_lock:
            return list(_memory_channels.get(claim_id, []))

    def subscribe(self, claim_id: int, timeout: float = 120.0) -> Iterator[dict[str, Any]]:
        for event in self.get_history(claim_id):
            yield event

        client = self.redis_client
        if not client:
            return

        pubsub = client.pubsub()
        pubsub.subscribe(self._channel(claim_id))
        try:
            seen = len(self.get_history(claim_id))
            elapsed = 0.0
            while elapsed < timeout:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    yield json.loads(message["data"])
                    if json.loads(message["data"]).get("step") == "completed":
                        break
                elapsed += 1.0
        finally:
            pubsub.close()


progress_service = ProgressService()
