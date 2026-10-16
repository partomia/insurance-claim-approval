"""
Stage 3 - MDM: one golden customer per real person, as of one business date.

Policy admin keys a customer per system: the core system's PA-C1xxxxx, the legacy branch
system's PA-C9xxxxx for policies sold there, often with the name keyed differently. The credit
bureau knows the same person by its own bureau_ref, with its own spelling and mobile format.

  match      policy-admin records -> one cluster per person (union-find), rules in order:
               EMAIL        same e-mail address                              score 1.00
               DOB_MOBILE   same date of birth and mobile (last 10 digits)   score 0.95
               DOB_NAME     same date of birth, same surname, first name equal,
                            an initial of it, or within edit distance 2      score 0.85
             then each cluster -> at most one bureau profile with the same date of birth:
               BUREAU_DOB_MOBILE  0.95, BUREAU_DOB_NAME 0.85 (as above); none -> NO_BUREAU_MATCH,
               two equally good -> AMBIGUOUS (not linked, both listed)
  survive    name: the most frequent full name keyed (an initial-only form never wins);
             mobile, city: the most recently changed policy; email: any (they agree);
             customer_since: earliest; bureau attributes from the linked profile
  publish    mdm.customer_golden, mdm.customer_xref (every source key -> golden id, rule,
             score), mdm.vehicle_xref (VIN -> policy, golden customer), mdm.match_exception

golden_customer_id = GC- + the first 10 hex of sha1(the cluster's lowest customer_ref): stable
across dates while the cluster keeps its members. The matching runs on the driver: a customer
master is thousands of rows, not millions; past ~1 M records this becomes blocking in Spark.

Usage:
  spark-submit build_mdm.py --business-date 2026-10-12 [--db-prefix P]
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcc_common as C  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

STAGE = "mdm"
GOLDEN_SCHEMA = (
    "golden_customer_id string, full_name string, dob date, mobile string, email string, city string, "
    "customer_since date, policies_held int, customer_refs array<string>, bureau_ref string, "
    "credit_score int, loan_defaults_12m int, active_vehicle_loan string, driver_age int, years_licensed int, "
    "traffic_violations_3y int, dui_history string, address_changed_90d string, other_insurer_claims_3y int, "
    "bureau_as_of date, match_confidence double, source_count int")
XREF_SCHEMA = ("golden_customer_id string, source_system string, source_key string, match_rule string, "
               "match_score double")
VEHICLE_SCHEMA = ("vin string, vehicle_reg_no string, vehicle_make string, vehicle_model string, vehicle_year int, "
                  "policy_number string, golden_customer_id string")
EXCEPTION_SCHEMA = "source_system string, source_key string, reason string, candidates string"
RULE_SCORE = {"EMAIL": 1.0, "DOB_MOBILE": 0.95, "DOB_NAME": 0.85, "SELF": 1.0,
              "BUREAU_DOB_MOBILE": 0.95, "BUREAU_DOB_NAME": 0.85}


def parser():
    return C.base_parser(__doc__)


# ---------------------------------------------------------------- matching (plain Python, tested)


def edit_distance(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _split(name: str | None) -> tuple[str, str]:
    parts = (name or "").split()
    return (parts[0], parts[-1]) if len(parts) >= 2 else ((parts[0], "") if parts else ("", ""))


def is_initial_form(name: str | None) -> bool:
    return len(_split(name)[0]) <= 1


def names_match(a: str | None, b: str | None) -> bool:
    fa, la = _split(a)
    fb, lb = _split(b)
    if not la or la != lb or not fa or not fb:
        return False
    if fa == fb:
        return True
    if len(fa) == 1 or len(fb) == 1:
        return fa[0] == fb[0]
    return edit_distance(fa, fb, 2) <= 2


class UnionFind:
    def __init__(self):
        self.parent: dict = {}
        self.rule: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b, rule):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)
            for k in (a, b):
                if RULE_SCORE[rule] < RULE_SCORE.get(self.rule.get(k, "SELF"), 1.0):
                    self.rule[k] = rule


def cluster_customers(records: list[dict]) -> tuple[dict, dict]:
    """records: one per customer_ref (name_norm, dob, mobile_norm, email). -> (ref -> root ref, ref -> rule)."""
    uf = UnionFind()
    for r in records:
        uf.find(r["customer_ref"])
    for key, rule in (("email", "EMAIL"), ("dob_mobile", "DOB_MOBILE")):
        groups = defaultdict(list)
        for r in records:
            k = r["email"] if key == "email" else ((r["dob"], r["mobile_norm"]) if r["dob"] and r["mobile_norm"] else None)
            if k:
                groups[k].append(r["customer_ref"])
        for refs in groups.values():
            for other in refs[1:]:
                uf.union(refs[0], other, rule)
    by_dob = defaultdict(list)
    for r in records:
        if r["dob"]:
            by_dob[r["dob"]].append(r)
    for rs in by_dob.values():
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                if names_match(a["name_norm"], b["name_norm"]):
                    uf.union(a["customer_ref"], b["customer_ref"], "DOB_NAME")
    roots = {r["customer_ref"]: uf.find(r["customer_ref"]) for r in records}
    return roots, {ref: uf.rule.get(ref, "SELF") for ref in roots}


def link_bureau(cluster: list[dict], bureau_by_dob: dict) -> tuple[dict | None, str | None, list]:
    """The bureau profile for a cluster: (profile, rule, candidates when ambiguous)."""
    dobs = {r["dob"] for r in cluster if r["dob"]}
    mobiles = {r["mobile_norm"] for r in cluster if r["mobile_norm"]}
    names = [r["name_norm"] for r in cluster]
    scored = []
    for dob in dobs:
        for b in bureau_by_dob.get(dob, []):
            if b["mobile_norm"] and b["mobile_norm"] in mobiles:
                scored.append((RULE_SCORE["BUREAU_DOB_MOBILE"], "BUREAU_DOB_MOBILE", b))
            elif any(names_match(n, b["name_norm"]) for n in names):
                scored.append((RULE_SCORE["BUREAU_DOB_NAME"], "BUREAU_DOB_NAME", b))
    if not scored:
        return None, None, []
    scored.sort(key=lambda x: -x[0])
    best = [s for s in scored if s[0] == scored[0][0]]
    if len({s[2]["bureau_ref"] for s in best}) > 1:
        return None, "AMBIGUOUS", [s[2]["bureau_ref"] for s in best]
    return best[0][2], best[0][1], []


def golden_id(refs) -> str:
    return "GC-" + hashlib.sha1(min(refs).encode()).hexdigest()[:10].upper()


def survive(cluster_policies: list[dict]) -> dict:
    names = Counter(p["holder_name"] for p in cluster_policies if p["holder_name"] and not is_initial_form(p["holder_name_norm"]))
    name = (max(names.items(), key=lambda kv: (kv[1], len(kv[0])))[0] if names
            else cluster_policies[0]["holder_name"])
    latest = max(cluster_policies, key=lambda p: (p["last_change_ts"] or datetime.min, p["policy_number"]))
    return {"full_name": name, "dob": latest["holder_dob"], "mobile": latest["holder_mobile_norm"],
            "email": next((p["holder_email"] for p in cluster_policies if p["holder_email"]), None),
            "city": latest["address_city"],
            "customer_since": min((p["customer_since"] for p in cluster_policies if p["customer_since"]), default=None),
            "policies_held": len({p["policy_number"] for p in cluster_policies})}


def resolve(policies: list[dict], bureau: list[dict]):
    """-> golden rows, xref rows, vehicle rows, exception rows (tuples in the *_SCHEMA order)."""
    by_ref = {}
    for p in sorted(policies, key=lambda p: p["last_change_ts"] or datetime.min, reverse=True):
        by_ref.setdefault(p["customer_ref"], {"customer_ref": p["customer_ref"], "name_norm": p["holder_name_norm"],
                                              "dob": p["holder_dob"], "mobile_norm": p["holder_mobile_norm"],
                                              "email": p["holder_email"]})
    roots, rules = cluster_customers(list(by_ref.values()))
    members = defaultdict(list)
    for ref, root in roots.items():
        members[root].append(ref)
    pols_by_ref = defaultdict(list)
    for p in policies:
        pols_by_ref[p["customer_ref"]].append(p)
    bureau_by_dob = defaultdict(list)
    for b in bureau:
        bureau_by_dob[b["dob"]].append(b)
    golden, xref, vehicles, exceptions = [], [], [], []
    linked = Counter()
    for root, refs in sorted(members.items()):
        gid = golden_id(refs)
        cp = [p for r in refs for p in pols_by_ref[r]]
        s = survive(cp)
        b, brule, cands = link_bureau([by_ref[r] for r in refs], bureau_by_dob)
        if brule == "AMBIGUOUS":
            exceptions.append(("POLICY_ADMIN", ",".join(sorted(refs)), "AMBIGUOUS_BUREAU", ",".join(sorted(cands))))
        elif b is None:
            exceptions.append(("POLICY_ADMIN", ",".join(sorted(refs)), "NO_BUREAU_MATCH", ""))
        else:
            linked[b["bureau_ref"]] += 1
        scores = [RULE_SCORE[rules[r]] for r in refs] + ([RULE_SCORE[brule]] if b is not None else [])
        golden.append((gid, s["full_name"], s["dob"], s["mobile"], s["email"], s["city"], s["customer_since"],
                       s["policies_held"], sorted(refs), b and b["bureau_ref"],
                       *(b and (b["credit_score"], b["loan_defaults_12m"], b["active_vehicle_loan"], b["driver_age"],
                                b["years_licensed"], b["traffic_violations_3y"], b["dui_history"],
                                b["address_changed_90d"], b["other_insurer_claims_3y"], b["as_of_date"])
                         or (None,) * 10),
                       float(min(scores)), len(refs) + (1 if b is not None else 0)))
        for r in sorted(refs):
            xref.append((gid, "POLICY_ADMIN", r, rules[r], RULE_SCORE[rules[r]]))
        if b is not None:
            xref.append((gid, "BUREAU", b["bureau_ref"], brule, RULE_SCORE[brule]))
        for p in cp:
            vehicles.append((p["vehicle_vin"], p["vehicle_reg_no"], p["vehicle_make"], p["vehicle_model"],
                             p["vehicle_year"], p["policy_number"], gid))
    for bref, n in linked.items():
        if n > 1:
            exceptions.append(("BUREAU", bref, "LINKED_TWICE", str(n)))
    linked_refs = set(linked)
    for b in bureau:
        if b["bureau_ref"] not in linked_refs:
            exceptions.append(("BUREAU", b["bureau_ref"], "NO_POLICY_HOLDER", ""))
    return golden, xref, vehicles, exceptions


# ---------------------------------------------------------------- run


def run(spark, argv=None) -> dict:
    args = C.parse(parser(), argv)
    names = C.Names(args.db_prefix)
    C.ensure_databases(spark, names)
    d = args.business_date
    C.require_completed(spark, names, "silver", d)
    day = F.lit(d.isoformat()).cast("date")
    audit = C.Audit(spark, names, "build_mdm", d, args.pipeline_run)
    audit.load(STAGE, "*", "STARTED")
    out = {}
    try:
        pol = spark.table(names.t("silver", "policy")).where(F.col("business_date") == day)
        bur = spark.table(names.t("silver", "bureau_profile")).where(F.col("business_date") == day)
        policies = [r.asDict() for r in pol.select(
            "policy_number", "customer_ref", "holder_name", "holder_name_norm", "holder_dob", "holder_mobile_norm",
            "holder_email", "address_city", "customer_since", "last_change_ts", "vehicle_vin", "vehicle_reg_no",
            "vehicle_make", "vehicle_model", "vehicle_year").collect()]
        bureau = [r.asDict() for r in bur.select(
            "bureau_ref", "name_norm", "dob", "mobile_norm", "credit_score", "loan_defaults_12m",
            "active_vehicle_loan", "driver_age", "years_licensed", "traffic_violations_3y", "dui_history",
            "address_changed_90d", "other_insurer_claims_3y", "as_of_date").collect()]
        golden, xref, vehicles, exceptions = resolve(policies, bureau)
        for name, rows, schema, ttype, sources in (
                ("customer_golden", golden, GOLDEN_SCHEMA, "survive", "silver.policy,silver.bureau_profile"),
                ("customer_xref", xref, XREF_SCHEMA, "match", "silver.policy,silver.bureau_profile"),
                ("vehicle_xref", vehicles, VEHICLE_SCHEMA, "match", "silver.policy"),
                ("match_exception", exceptions, EXCEPTION_SCHEMA, "validate", "silver.policy,silver.bureau_profile")):
            target = names.t("mdm", name)
            before = C.snapshot_id(spark, target)
            df = spark.createDataFrame(rows, schema).withColumn("business_date", day)
            C.write_partitions(df, target, ["business_date"])
            audit.load(STAGE, name, "COMMITTED", rows_in=len(policies) + len(bureau), rows_out=len(rows),
                       snapshot_before=before, snapshot_after=C.snapshot_id(spark, target))
            audit.transform(f"build {name}", ttype, sources, target, len(policies) + len(bureau), len(rows))
            out[name] = len(rows)
        reasons = Counter(e[2] for e in exceptions)
        merged = sum(1 for g in golden if len(g[8]) > 1)
        refs = {r["customer_ref"] for r in policies}
        print(f"mdm: {len(refs)} customer refs -> {len(golden)} golden "
              f"({merged} merged across systems), {sum(1 for g in golden if g[9])} linked to the bureau; "
              f"exceptions {dict(reasons)}", flush=True)
        audit.load(STAGE, "*", "COMPLETED", rows_in=len(refs), rows_out=len(golden),
                   message=f"exceptions {dict(reasons)}")
    except Exception as e:
        audit.load(STAGE, "*", "FAILED", message=C.error_summary(e))
        raise
    finally:
        audit.flush()
    return out


def main() -> int:
    spark = C.get_spark("mcc-build-mdm")
    run(spark, sys.argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
