"""
One business date's source files, as the five source systems deliver them, plus _manifest.json per
source folder (record counts and control totals as the SOURCE reports them; reconciliation is
always against the manifest).

  garages/<d>/garages_<yyyymmdd>.csv                 day 1 only
  policy_admin/<d>/policies_<yyyymmdd>.csv           day 1 full extract
  policy_admin/<d>/clauses_<yyyymmdd>.csv            day 1
  policy_admin/<d>/policy_cdc_<yyyymmdd>.jsonl       later days (Debezium-style after-images)
  bureau/<d>/bureau_<yyyymmdd>.psv                   day 1 full, later days deltas, trailer T|count|sum
  claims/<d>/claims_<yyyymmdd>.jsonl                 FNOL of the day (day 1 also the 24-month history)
  claims/<d>/claim_status_<yyyymmdd>.jsonl           status transitions with event time on the day
  telematics/<d>/crash_events_<yyyymmdd>.jsonl       day 1 only: vendor bulk export before the stream

Planted faults (validation, quarantine and reconciliation must find them):
  day 1  a re-sent policy row with a malformed VIN (reject); one policy without holder_email (warn)
  day 2  a CDC event for an unknown policy; the day-1 claim CLM of the first FNOL re-sent (dedup)
  day 3  the bureau trailer count is off by one (recon MISMATCH); one status event of day 2 arrives
         a day late (out of order)
  day 4  a claim against a policy that does not exist (orphan, quarantined at silver)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta

from generators.universe import DATES, R, World, ts

ENTITY_FILES = {  # entity -> (source, file pattern)
    "gn_garage": ("garages", "garages_{d}.csv"),
    "pa_policy": ("policy_admin", "policies_{d}.csv"),
    "pa_clause": ("policy_admin", "clauses_{d}.csv"),
    "pa_policy_cdc": ("policy_admin", "policy_cdc_{d}.jsonl"),
    "bu_profile": ("bureau", "bureau_{d}.psv"),
    "cl_claim": ("claims", "claims_{d}.jsonl"),
    "cl_claim_status": ("claims", "claim_status_{d}.jsonl"),
    "tm_crash": ("telematics", "crash_events_{d}.jsonl"),
}
CONTROL = {"pa_policy": "premium_amount", "bu_profile": "credit_score", "cl_claim": "amount_requested"}


def _csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def _jsonl(rows: list[dict]) -> bytes:
    return "".join(json.dumps(r, sort_keys=False) + "\n" for r in rows).encode()


def _psv(rows: list[dict], control: str, count_offset: int = 0) -> bytes:
    if not rows:
        return b""
    cols = list(rows[0])
    lines = ["|".join(cols)] + ["|".join("" if r[c] is None else str(r[c]) for c in cols) for r in rows]
    total = sum(float(r[control] or 0) for r in rows)
    lines.append(f"T|{len(rows) + count_offset}|{total:.2f}")
    return ("\n".join(lines) + "\n").encode()


def _total(rows: list[dict], field: str) -> float:
    return round(sum(float(r.get(field) or 0) for r in rows), 2)


def records_for(world: World, d: date) -> dict[str, list[dict]]:
    """entity -> the records the sources deliver for business date d."""
    i = DATES.index(d)
    day_start = datetime.combine(d, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    rng = R(world.seed, f"land:{d}")
    out: dict[str, list[dict]] = {}

    if i == 0:
        out["gn_garage"] = list(world.garages)
        pol = [dict(r) for r in world.day1_policies]
        extra = [r for r in pol if r["policy_number"] >= "LH-POL-2800"]
        bad = dict(extra[0])
        bad["vehicle_vin"] = "MA12"
        pol.append(bad)
        extra[1]["holder_email"] = ""
        out["pa_policy"] = pol
        out["pa_clause"] = [{"policy_number": p.policy_number, "section_ref": s, "title": t, "content_text": x}
                            for p in world.policies.values() for t, s, x in _clauses()]
        out["bu_profile"] = [world.bureau_row(R(world.seed, f"bureau:{c.idx}:{d}"), c, d) for c in world.customers]
        hist = [cl for cl in world.claims if cl.fnol < day_start]
        out["cl_claim"] = [world.claim_row(cl, day_start, R(world.seed, f"claimrow:{cl.claim_id}")) for cl in hist]
        out["tm_crash"] = [e for e in world.crash_events if e["event_ts"] < ts(day_start)]
    else:
        cdc = list(world.cdc[d])
        if i == 1:
            cdc.append({"op": "u", "ts_ms": cdc[0]["ts_ms"] + 1000, "policy_number": "LH-POL-9999",
                        "after": json.dumps({"policy_number": "LH-POL-9999", "status": "ACTIVE"})})
        out["pa_policy_cdc"] = cdc
        changed = rng.sample(world.customers, max(1, len(world.customers) // 20))
        out["bu_profile"] = [world.bureau_row(R(world.seed, f"bureau:{c.idx}:{d}"), c, d)
                             for c in sorted(changed, key=lambda c: c.idx)]

    fnol = [cl for cl in world.claims if day_start <= cl.fnol < day_end]
    rows = [world.claim_row(cl, day_end, R(world.seed, f"claimrow:{cl.claim_id}")) for cl in fnol]
    out["cl_claim"] = out.get("cl_claim", []) + rows
    if i == 1:
        first = next(cl for cl in world.claims if cl.fnol >= datetime.combine(DATES[0], datetime.min.time()))
        out["cl_claim"].append(world.claim_row(first, day_start, R(world.seed, f"claimrow:{first.claim_id}")))
    if i == 3:
        orphan = dict(rows[0])
        orphan.update(claim_id="CLM-999001", policy_number="LH-POL-9998")
        out["cl_claim"].append(orphan)

    events = sorted((e for cl in world.claims for e in world.status_events(cl)), key=lambda x: x[0])
    late = _late_event(events, DATES[1]) if len(DATES) > 2 else None
    status = [ev for t, ev in events if day_start <= t < day_end and ev is not late]
    if i == 2 and late is not None:
        status.append(late)
    out["cl_claim_status"] = status
    return out


def _late_event(events, d: date):
    start = datetime.combine(d, datetime.min.time())
    return next((ev for t, ev in events if start <= t < start + timedelta(days=1) and ev["to_status"] == "APPROVED"), None)


def _clauses():
    from generators.universe import CLAUSES
    return CLAUSES


def files_for(world: World, d: date) -> dict[str, dict[str, bytes]]:
    """source -> {file name: bytes}, including _manifest.json."""
    recs = records_for(world, d)
    stamp = d.strftime("%Y%m%d")
    out: dict[str, dict[str, bytes]] = {}
    manifests: dict[str, dict] = {}
    for entity, rows in recs.items():
        source, pattern = ENTITY_FILES[entity]
        name = pattern.format(d=stamp)
        fmt = name.rsplit(".", 1)[1]
        if fmt == "csv":
            data = _csv(rows)
        elif fmt == "psv":
            data = _psv(rows, CONTROL[entity], count_offset=1 if (entity == "bu_profile" and DATES.index(d) == 2) else 0)
        else:
            data = _jsonl(rows)
        if not data:
            continue
        out.setdefault(source, {})[name] = data
        m = manifests.setdefault(source, {"source": source, "business_date": d.isoformat(), "files": []})
        m["files"].append({"name": name, "entity": entity, "records": len(rows), "size": len(data),
                           "sha256": hashlib.sha256(data).hexdigest(),
                           **({"control_field": CONTROL[entity], "control_total": _total(rows, CONTROL[entity])}
                              if entity in CONTROL else {})})
    for source, m in manifests.items():
        out[source]["_manifest.json"] = json.dumps(m, indent=2).encode()
    return out
