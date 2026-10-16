"""MDM matching on the generated sources, scored against the generator's truth (no Spark)."""
import random
import re
from datetime import datetime

import pytest

from build_mdm import edit_distance, golden_id, names_match, resolve
from generators.universe import World


def _norm_mobile(s):
    d = re.sub(r"[^0-9]", "", s or "")
    return d[-10:] if len(d) >= 10 else None


def _norm_name(s):
    return re.sub(r"[^A-Z ]", "", (s or "").upper()).strip()


@pytest.fixture(scope="module")
def resolved():
    w = World()
    policies = []
    for p in w.policies.values():
        row = w.policy_row(p, datetime.combine(p.effective, datetime.min.time()))
        policies.append({
            "policy_number": p.policy_number, "customer_ref": row["customer_ref"], "holder_name": row["holder_name"],
            "holder_name_norm": _norm_name(row["holder_name"]), "holder_dob": p.customer.dob,
            "holder_mobile_norm": _norm_mobile(row["holder_mobile"]), "holder_email": row["holder_email"],
            "address_city": row["address_city"], "customer_since": p.customer.customer_since,
            "last_change_ts": datetime.combine(p.effective, datetime.min.time()), "vehicle_vin": p.vin,
            "vehicle_reg_no": p.reg_no, "vehicle_make": p.make, "vehicle_model": p.model, "vehicle_year": p.year})
    bureau = []
    for c in w.customers:
        b = w.bureau_row(random.Random(c.idx), c, w.anchor)
        bureau.append({"bureau_ref": b["bureau_ref"], "name_norm": _norm_name(b["full_name"]), "dob": c.dob,
                       "mobile_norm": _norm_mobile(b["mobile"]), "credit_score": int(b["credit_score"]),
                       "loan_defaults_12m": 0, "active_vehicle_loan": "N", "driver_age": 40, "years_licensed": 10,
                       "traffic_violations_3y": 0, "dui_history": "N", "address_changed_90d": "N",
                       "other_insurer_claims_3y": 0, "as_of_date": w.anchor})
    return w, resolve(policies, bureau)


def test_clusters_match_truth(resolved):
    w, (golden, xref, _, exceptions) = resolved
    truth = {frozenset(v["customer_refs"]) for v in w.truth()["customers"].values()}
    got = {frozenset(g[8]) for g in golden}
    assert got == truth
    assert len(golden) == len(w.customers)


def test_bureau_links_match_truth(resolved):
    w, (golden, *_rest) = resolved
    truth = {min(v["customer_refs"]): v["bureau_ref"] for v in w.truth()["customers"].values()}
    linked = {min(g[8]): g[9] for g in golden}
    wrong = [k for k, b in linked.items() if b is not None and b != truth[k]]
    assert not wrong
    assert sum(b is not None for b in linked.values()) >= 0.97 * len(linked)


def test_golden_id_is_stable_and_name_survives_full_form(resolved):
    _, (golden, *_rest) = resolved
    for g in golden:
        assert g[0] == golden_id(g[8])
        assert len(g[1].split()[0]) > 2


def test_name_rules():
    assert names_match("ANANYA IYER", "A IYER")
    assert names_match("ANANYA IYER", "ANNAYA IYER")
    assert not names_match("ANANYA IYER", "ANANYA RAO")
    assert edit_distance("KITTEN", "SITTING") == 3
