import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import governance as g  # noqa: E402

GOV = json.loads((ROOT / "config" / "governance.json").read_text())
KPI = json.loads((ROOT / "config" / "kpi.json").read_text())


def test_column_tag_by_name_and_type():
    assert g.column_tag(GOV, "Full_Name", "string") == "MCC_SENSITIVE_HASH"
    assert g.column_tag(GOV, "dob", "date") == "MCC_SENSITIVE_DOB"
    assert g.column_tag(GOV, "dob", "string") == "MCC_SENSITIVE_HASH"
    assert g.column_tag(GOV, "credit_score", "int") == "MCC_SENSITIVE_FINANCIAL"
    assert g.column_tag(GOV, "claim_id", "string") is None


def test_every_column_rule_names_a_classification():
    tags = set(GOV["classifications"])
    for rule in GOV["columns"].values():
        assert set(rule.values() if isinstance(rule, dict) else [rule]) <= tags


def test_classification_changes_only_touch_mcc_tags():
    cols = [
        {"guid": "1", "qualifiedName": "s.t.mobile@cm", "name": "mobile", "type": "string", "tags": []},
        {"guid": "2", "qualifiedName": "s.t.claim_id@cm", "name": "claim_id", "type": "string",
         "tags": ["MCC_SENSITIVE_HASH", "OTHER_TAG"]},
        {"guid": "3", "qualifiedName": "s.t.email@cm", "name": "email", "type": "string",
         "tags": ["MCC_SENSITIVE_HASH"]},
    ]
    adds, removes = g.classification_changes(GOV, cols)
    assert adds == [("1", "s.t.mobile@cm", "MCC_SENSITIVE_CONTACT")]
    assert removes == [("2", "s.t.claim_id@cm", "MCC_SENSITIVE_HASH")]


def test_masking_policy_masks_federal01_only():
    p = g.masking_policy(GOV, "MCC_SENSITIVE_FINANCIAL")
    assert p["name"] == "rsingh-mcc-sensitive-financial"
    assert p["service"] == "cm_tag"
    item = p["dataMaskPolicyItems"][0]
    assert item["users"] == ["federal01"]
    assert item["dataMaskInfo"]["dataMaskType"] == "hive:MASK_NULL"
    assert not g.policy_differs(p, json.loads(json.dumps(p)))
    assert g.policy_differs(p, {**p, "isEnabled": False})


def test_glossary_terms_cover_every_kpi():
    terms = g.glossary_terms(GOV, KPI)
    assert {t["abbreviation"] for t in terms} == {"STP", "CCT", "LR"}
    for t in terms:
        assert t["assigned_to"] and "Certified view:" in t["longDescription"]
