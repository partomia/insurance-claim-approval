from datetime import datetime
from types import SimpleNamespace

import pytest

from models.claim import ClaimStatus, IncidentType
from services import approval_model_service as svc


def _claim(**kw):
    base = dict(id=1, claim_number="CLM-1", incident_type=IncidentType.COLLISION, claim_amount=42000.0,
                incident_datetime=datetime(2026, 10, 15, 20, 5), created_at=datetime(2026, 10, 16, 9, 0),
                vin="VIN1", policy=SimpleNamespace(policy_number="POL-1"), status=ClaimStatus.APPROVED,
                model_prediction_json=None, updated_at=datetime(2026, 10, 16, 9, 1))
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def shadow(monkeypatch):
    monkeypatch.setattr(svc.settings, "approval_model_mode", "shadow")
    monkeypatch.setattr(svc.settings, "approval_model_url", "https://modelservice.example/model")
    monkeypatch.setattr(svc.settings, "approval_model_access_key", "ak")
    monkeypatch.setattr(svc.settings, "approval_model_api_key", "k")
    monkeypatch.setattr(svc, "policy_context", lambda n: {"policy_number": n, "golden_customer_id": "G1"})


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_off_by_default_never_calls(monkeypatch):
    monkeypatch.setattr(svc.settings, "approval_model_mode", "off")
    monkeypatch.setattr(svc.requests, "post", lambda *a, **k: pytest.fail("called"))
    assert svc.score_and_store(None, _claim(), "APPROVED") is None


def test_shadow_stores_the_answer_and_sends_only_final_decisions(shadow, monkeypatch):
    sent = []

    def post(url, json, headers, timeout):
        sent.append(json)
        return _Resp({"response": {"p_approve": 0.8, "p_fraud": 0.01, "approval_band": "LIKELY_APPROVE",
                                   "fraud_band": "CLEAR", "agrees_with_rules": True, "customer_visible": False,
                                   "model": {"approval": {"version": "approval-1", "test_auroc": 0.79}}}})

    monkeypatch.setattr(svc.requests, "post", post)
    db = SimpleNamespace(commit=lambda: None)
    claim = _claim()
    rec = svc.score_and_store(db, claim, "APPROVED")
    assert claim.model_prediction_json is rec
    assert rec["p_approve"] == 0.8 and rec["agrees_with_rules"] is True and rec["policy_in_lakehouse"]
    assert rec["model"]["approval"]["version"] == "approval-1"
    req = sent[0]["request"]
    assert req["claim"]["claim_type"] == "Collision" and req["claim"]["fnol_ts"].startswith("2026-10-16")
    assert req["rules_decision"] == "APPROVED"
    svc.score(_claim(), "PENDING_REVIEW")
    assert sent[1]["request"]["rules_decision"] is None


def test_failures_are_recorded_not_raised(shadow, monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(svc.requests, "post", boom)
    rec = svc.score(_claim(), "APPROVED")
    assert rec["error"].startswith("TimeoutError")
    monkeypatch.setattr(svc.requests, "post", lambda *a, **k: _Resp({"response": {"error": "bad row"}}))
    assert svc.score(_claim(), "APPROVED")["error"] == "bad row"


def test_model_vs_rules():
    rows = [
        # scored at ANALYSIS_COMPLETE, approved by the insurer later: compared with that
        _claim(id=1, model_prediction_json={"approval_band": "LIKELY_APPROVE", "rules_decision": "ANALYSIS_COMPLETE",
                                            "fraud_band": "CLEAR"}),
        _claim(id=2, claim_number="CLM-2", status=ClaimStatus.REJECTED,
               model_prediction_json={"approval_band": "LIKELY_APPROVE", "rules_decision": "REJECTED",
                                      "fraud_band": "FRAUD_REVIEW"}),
        _claim(id=3, model_prediction_json={"approval_band": "UNCERTAIN"}),
        _claim(id=4, model_prediction_json={"error": "TimeoutError"}),
        _claim(id=5, status=ClaimStatus.PENDING_REVIEW, model_prediction_json={"approval_band": "REVIEW"}),
    ]

    class Q:
        def filter(self, *a):
            return self

        def order_by(self, *a):
            return self

        def all(self):
            return rows

    out = svc.model_vs_rules(SimpleNamespace(query=lambda m: Q()))
    assert (out["scored"], out["errors"], out["compared"], out["agreement_rate"]) == (4, 1, 2, 0.5)
    assert out["fraud_review"] == 1
    assert [d["claim_number"] for d in out["disagreements"]] == ["CLM-2"]
    assert svc.view(rows[0])["agrees_with_rules"] is True and svc.view(rows[0])["rules_decision"] == "APPROVED"
    assert svc.view(rows[4])["agrees_with_rules"] is None and svc.view(rows[3]) == {"error": "TimeoutError"}
