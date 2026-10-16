"""Shadow-mode claim model: scores a decided claim on the Cloudera AI endpoint
`mcc-approval` (serve/predict.py, both heads) and keeps the result on
Claim.model_prediction_json for insurers and agents.

The rules decision is never changed: the call happens after it is persisted,
any failure is recorded and swallowed, and APPROVAL_MODEL_MODE=off (default)
skips it entirely. Policy features come from the lakehouse scoring context
(<LAKEHOUSE_DATABASE>.scoring_context_policy, by policy number); the app has
no garage master, so garage features are left to the model's defaults.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from config import get_settings
from models.claim import IncidentType

logger = logging.getLogger(__name__)
settings = get_settings()

MODES = ("off", "shadow")

CLAIM_TYPE = {
    IncidentType.COLLISION: "Collision",
    IncidentType.THEFT: "Theft",
    IncidentType.FIRE: "Fire",
    IncidentType.NATURAL_DISASTER: "NaturalDisaster",
    IncidentType.GLASS_ONLY: "Glass",
    IncidentType.THIRD_PARTY_LIABILITY: "ThirdParty",
    IncidentType.VANDALISM: "Vandalism",
    IncidentType.OTHER: "Other",
}

# Only a final rules outcome is compared; a claim sent to review is neither.
COMPARABLE = {"APPROVED", "REJECTED"}

KEEP = ("p_approve", "p_fraud", "approval_band", "fraud_band", "band_reason", "agrees_with_rules",
        "top_factors", "guardrails", "guardrail_events", "action", "customer_visible")

_CONTEXT_TTL_S = 600
_context_cache: dict[str, tuple[float, dict | None]] = {}


def mode() -> str:
    m = (settings.approval_model_mode or "off").strip().lower()
    return m if m in MODES else "off"


def enabled() -> bool:
    return mode() != "off" and bool(settings.approval_model_url and settings.approval_model_access_key)


def _api_key() -> str:
    return settings.approval_model_api_key or os.environ.get("CDSW_APIV2_KEY", "")


def policy_context(policy_number: str | None) -> dict | None:
    """The policy's scoring-context row from the lakehouse (cached 10 min)."""
    if not policy_number:
        return None
    hit = _context_cache.get(policy_number)
    if hit and time.monotonic() - hit[0] < _CONTEXT_TTL_S:
        return hit[1]
    from database import _impala_connect

    conn = _impala_connect(database=settings.lakehouse_database)
    try:
        cur = conn.cursor()
        safe = policy_number.replace("'", "''")
        cur.execute(f"SELECT * FROM {settings.lakehouse_database}.scoring_context_policy "
                    f"WHERE policy_number = '{safe}' LIMIT 1")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        row = {c: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in zip(cols, rows[0])} if rows else None
    finally:
        conn.close()
    _context_cache[policy_number] = (time.monotonic(), row)
    return row


def claim_payload(claim) -> dict[str, Any]:
    filed = claim.created_at or datetime.utcnow()
    return {
        "claim_type": CLAIM_TYPE.get(claim.incident_type, "Other"),
        "amount_requested": float(claim.claim_amount or 0.0),
        "incident_ts": claim.incident_datetime.isoformat() if claim.incident_datetime else None,
        "fnol_ts": filed.isoformat(),
        "vehicle_vin": claim.vin,
    }


def score(claim, rules_decision: str | None) -> dict[str, Any]:
    """The stored record for one claim: the model's answer, or why there is none."""
    record: dict[str, Any] = {"mode": mode(), "scored_at": datetime.now(timezone.utc).isoformat(),
                              "rules_decision": rules_decision}
    policy_number = claim.policy.policy_number if claim.policy else None
    try:
        policy = policy_context(policy_number)
        rules = rules_decision if rules_decision in COMPARABLE else None
        body = {"accessKey": settings.approval_model_access_key,
                "request": {"claim": claim_payload(claim), "policy": policy, "rules_decision": rules}}
        headers = {"Authorization": f"Bearer {_api_key()}"} if _api_key() else {}
        r = requests.post(settings.approval_model_url, json=body, headers=headers,
                          timeout=settings.approval_model_timeout_s)
        r.raise_for_status()
        res = r.json().get("response") or {}
        if res.get("error"):
            record["error"] = str(res["error"])[:300]
            return record
        record.update({k: res.get(k) for k in KEEP})
        record["model"] = {head: {k: m.get(k) for k in ("version", "registry_name", "registry_version", "test_auroc")}
                           for head, m in (res.get("model") or {}).items()}
        record["policy_in_lakehouse"] = policy is not None
    except Exception as e:  # noqa: BLE001 - shadow mode never breaks the claim pipeline
        logger.warning("approval model call failed for claim %s: %s", claim.id, e)
        record["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return record


def model_vs_rules(db, limit: int = 20) -> dict[str, Any]:
    """Insurer dashboard: how often the shadow model agrees with the rules, and the
    claims where it does not (newest first) for a reviewer to look at."""
    from models.claim import Claim

    claims = (db.query(Claim).filter(Claim.model_prediction_json.isnot(None))
              .order_by(Claim.updated_at.desc()).all())
    scored = [c for c in claims if not (c.model_prediction_json or {}).get("error")]
    compared = [c for c in scored if c.model_prediction_json.get("agrees_with_rules") is not None]
    agree = sum(1 for c in compared if c.model_prediction_json["agrees_with_rules"])
    disagreements = [
        {"claim_id": c.id, "claim_number": c.claim_number, "status": c.status.value,
         "rules_decision": c.model_prediction_json.get("rules_decision"),
         "approval_band": c.model_prediction_json.get("approval_band"),
         "fraud_band": c.model_prediction_json.get("fraud_band"),
         "p_approve": c.model_prediction_json.get("p_approve"),
         "p_fraud": c.model_prediction_json.get("p_fraud"),
         "scored_at": c.model_prediction_json.get("scored_at")}
        for c in compared if not c.model_prediction_json["agrees_with_rules"]
    ]
    return {
        "mode": mode(),
        "scored": len(scored),
        "errors": len(claims) - len(scored),
        "compared": len(compared),
        "agreement_rate": round(agree / len(compared), 4) if compared else None,
        "fraud_review": sum(1 for c in scored if c.model_prediction_json.get("fraud_band") == "FRAUD_REVIEW"),
        "disagreements": disagreements[:limit],
    }


def score_and_store(db, claim, rules_decision: str | None) -> dict | None:
    if not enabled():
        return None
    record = score(claim, rules_decision)
    claim.model_prediction_json = record
    db.commit()
    return record
