"""Generators and the bronze parsers without Spark: the seeded universe, the manifests, and
the planted source faults bronze and recon must catch."""
import hashlib
import json
import re
from datetime import date

import pytest

import mcc_common as C
from generators.landing import files_for
from generators.universe import DATES, World


@pytest.fixture(scope="module")
def world():
    return World()


def test_world_is_deterministic(world):
    again = World()
    assert [c.claim_id for c in again.claims] == [c.claim_id for c in world.claims]
    assert files_for(again, DATES[1]) == files_for(world, DATES[1])


def test_outcome_mix(world):
    decided = [c for c in world.claims if c.status in ("APPROVED", "REJECTED")]
    approved = sum(c.status == "APPROVED" for c in decided) / len(decided)
    fraud = sum(c.fraud for c in world.claims) / len(world.claims)
    assert 0.75 <= approved <= 0.88
    assert 0.03 <= fraud <= 0.10
    assert {c.decided_by for c in decided} == {"AUTO", "ADJUSTER", "FRAUD_SIU"}


def test_manifest_matches_files(world):
    for d in DATES[:5]:
        for source, files in files_for(world, d).items():
            m = json.loads(files["_manifest.json"])
            for f in m["files"]:
                data = files[f["name"]]
                assert hashlib.sha256(data).hexdigest() == f["sha256"] and len(data) == f["size"]


def _rows(files, entity):
    contract = C.contracts()[entity]
    cols = [c["name"] for c in contract["columns"]]
    m = json.loads(files["_manifest.json"])
    f = next(x for x in m["files"] if x["entity"] == entity)
    text = files[f["name"]].decode()
    parse = {"csv": C.parse_csv, "psv": C.parse_psv, "jsonl": C.parse_jsonl}[contract["format"]]
    return cols, list(parse(f["name"], text, cols)), f, text


def test_day1_policy_faults(world):
    cols, rows, f, _ = _rows(files_for(world, DATES[0])["policy_admin"], "pa_policy")
    assert len(rows) == f["records"]
    vin = cols.index("vehicle_vin") + 2
    email = cols.index("holder_email") + 2
    pattern = next(c["pattern"] for c in C.contracts()["pa_policy"]["columns"] if c["name"] == "vehicle_vin")
    assert sum(not re.match(pattern, r[vin] or "") for r in rows) == 1
    assert sum(r[email] is None for r in rows) == 1


def test_bureau_trailer_off_by_one_on_day3(world):
    for i in (1, 2):
        cols, rows, f, text = _rows(files_for(world, DATES[i])["bureau"], "bu_profile")
        _, _, data, trailer, total = C.psv_stats(f["name"], text)
        assert data == len(rows) == f["records"]
        assert round(total, 2) == f["control_total"]
        assert (trailer != data) == (i == 2)


def test_orphan_claim_and_unknown_policy_cdc(world):
    cdc = files_for(world, DATES[1])["policy_admin"]
    assert b"LH-POL-9999" in next(v for k, v in cdc.items() if k.startswith("policy_cdc"))
    claims = files_for(world, DATES[3])["claims"]
    assert b"CLM-999001" in next(v for k, v in claims.items() if k.startswith("claims_"))


def test_contract_formats_cover_all_entities():
    contracts = C.contracts()
    assert set(contracts) == set(C.CFG["entities"])
    for c in contracts.values():
        assert c["format"] in ("csv", "psv", "jsonl")
        for col in c["columns"]:
            if col["type"] == "timestamp":
                assert "format" in col


def test_scheduled_dates_have_claims(world):
    for d in C.CFG["scheduled_dates"]:
        assert "claims" in files_for(world, date.fromisoformat(d))
