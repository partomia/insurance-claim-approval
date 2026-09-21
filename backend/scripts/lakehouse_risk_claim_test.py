"""Reusable test harness for the lakehouse risk -> decision pipeline (Phase 4b,
see cde/README.md "Feed fraud_risk_score/claim_risk_band into the live
decision engine"). Replaces the one-off curl chains we were hand-typing in
chat to verify this — same spirit as verify_phase4.sh / set_demo_password.py /
generate_demo_claim_docs.py: an ad-hoc test becomes a committed, reusable tool.

Two subcommands:

  find    — DB-direct (no running app needed). Lists lakehouse-ingested
            policies (PolicyRiskSignal rows) filtered by risk band / status,
            so you can pick one to test against.

  submit  — end-to-end HTTP test against a *running* app instance: sets a
            known password for the policy's customer (reuses the same
            mechanism as set_demo_password.py), logs in, creates a draft
            claim, links it to the given policy, fetches policy context,
            uploads the committed synthetic evidence docs
            (docs/demo-assets/claim-docs/), submits, polls for the decision,
            and prints a clean summary (status, fraud_score,
            escalation_flags/messages, reasoning) — exactly what you'd want
            to confirm the lakehouse_high_risk_policy signal actually fired
            and drove the outcome.

Usage (via cml/cli.sh, run from repo root):
    bash cml/cli.sh test-claim find --band HIGH --active-only
    bash cml/cli.sh test-claim submit --policy-number LH-POL-2059

Or directly:
    cd backend
    uv run python scripts/lakehouse_risk_claim_test.py find --band HIGH --active-only
    uv run python scripts/lakehouse_risk_claim_test.py submit --policy-number LH-POL-2059 \\
        --base-url http://127.0.0.1:8099

NOT for production use — directly rewrites the customer's password like
set_demo_password.py. Intended for local/CML demo databases only.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal  # noqa: E402
from dependencies import get_password_hash  # noqa: E402
from models.customer import Customer  # noqa: E402
from models.policy import Policy  # noqa: E402
from models.policy_risk_signal import PolicyRiskSignal  # noqa: E402

DEMO_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "demo-assets" / "claim-docs"
DEFAULT_PASSWORD = "password123"
DEFAULT_OTP = "112233"


def cmd_find(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        query = (
            db.query(Policy, PolicyRiskSignal, Customer)
            .join(PolicyRiskSignal, PolicyRiskSignal.policy_id == Policy.id)
            .join(Customer, Customer.id == Policy.customer_id)
        )
        if args.band:
            query = query.filter(PolicyRiskSignal.claim_risk_band == args.band.upper())
        rows = query.order_by(PolicyRiskSignal.fraud_risk_score.desc()).all()
        if args.active_only:
            rows = [r for r in rows if r[0].status.value != "EXPIRED"]
        if not rows:
            print("No matching policies found. Try without --active-only, or run "
                  "'bash cml/cli.sh lakehouse ingest' first if the DB has no risk signals yet.")
            return
        print(f"{'policy_number':<14} {'status':<10} {'band':<8} {'score':>6} {'claims':>7}  customer_email")
        for policy, rs, customer in rows[: args.limit]:
            print(
                f"{policy.policy_number:<14} {policy.status.value:<10} {rs.claim_risk_band:<8} "
                f"{rs.fraud_risk_score:>6.1f} {rs.total_claims_count:>7}  {customer.email}"
            )
    finally:
        db.close()


def _ensure_password(email: str, password: str) -> None:
    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.email == email).first()
        if not customer:
            print(f"[error] No customer found with email={email}", file=sys.stderr)
            sys.exit(1)
        customer.hashed_password = get_password_hash(password)
        db.commit()
        print(f"[ok] Password set for {email}")
    finally:
        db.close()


def _lookup_customer_email(policy_number: str) -> str:
    db = SessionLocal()
    try:
        policy = db.query(Policy).filter(Policy.policy_number == policy_number).first()
        if not policy or not policy.customer:
            print(f"[error] Policy {policy_number} not found or has no linked customer", file=sys.stderr)
            sys.exit(1)
        return policy.customer.email
    finally:
        db.close()


def cmd_submit(args: argparse.Namespace) -> None:
    email = args.email or _lookup_customer_email(args.policy_number)
    _ensure_password(email, args.password)

    base = args.base_url.rstrip("/")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        client.post("/auth/login", json={"email": email, "password": args.password})
        resp = client.post("/auth/verify-otp", json={"email": email, "otp": args.otp})
        resp.raise_for_status()
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"[ok] Logged in as {email}")

        draft_resp = client.post(
            "/api/claims/draft",
            headers=headers,
            json={
                "incident_description": args.incident_description,
                "incident_datetime": args.incident_datetime,
                "location": args.location,
                "claim_amount": args.claim_amount,
                "incident_type": args.incident_type,
                "driver_license_number": "DL-TEST-0000",
            },
        )
        draft_resp.raise_for_status()
        claim_id = draft_resp.json()["id"]
        print(f"[ok] Draft claim created: id={claim_id}")

        patch_resp = client.patch(
            f"/api/claims/{claim_id}/draft",
            headers=headers,
            json={"policy_number": args.policy_number},
        )
        patch_resp.raise_for_status()
        print(f"[ok] Linked to policy {args.policy_number}")

        fetch_resp = client.post(f"/api/claims/{claim_id}/policy-documents/fetch", headers=headers)
        if fetch_resp.status_code != 200:
            print(f"[warn] policy-documents/fetch -> {fetch_resp.status_code}: {fetch_resp.text[:200]}")
        else:
            print("[ok] Policy context fetched from DB")

        opened = []

        def _open(name: str):
            f = open(DEMO_DOCS_DIR / name, "rb")
            opened.append(f)
            return f

        try:
            files_payload = [
                ("damage_photos", ("damage_photo_front.jpg", _open("damage_photo_front.jpg"), "image/jpeg")),
                ("driver_license", ("driver_license.jpg", _open("driver_license.jpg"), "image/jpeg")),
                ("vehicle_registration", ("vehicle_registration.jpg", _open("vehicle_registration.jpg"), "image/jpeg")),
                ("police_report", ("police_report.jpg", _open("police_report.jpg"), "image/jpeg")),
            ]
            ev_resp = client.post(f"/api/claims/{claim_id}/evidence", headers=headers, files=files_payload)
        finally:
            for f in opened:
                f.close()
        if ev_resp.status_code != 200:
            print(f"[error] evidence upload failed: {ev_resp.status_code} {ev_resp.text}", file=sys.stderr)
            sys.exit(1)
        print("[ok] Evidence uploaded")

        submit_resp = client.post(f"/api/claims/{claim_id}/submit", headers=headers)
        submit_resp.raise_for_status()
        print(f"[ok] Submitted: {submit_resp.json()}")

        print(f"Waiting for pipeline (up to {args.wait_seconds}s)", end="", flush=True)
        decision_data = None
        for _ in range(args.wait_seconds):
            time.sleep(1)
            print(".", end="", flush=True)
            status_resp = client.get(f"/api/claims/{claim_id}/status", headers=headers)
            status_resp.raise_for_status()
            data = status_resp.json()
            if data.get("decision"):
                decision_data = data
                break
        print()

        if not decision_data:
            print(
                f"[warn] Pipeline did not finish within {args.wait_seconds}s — check manually: "
                f"GET /api/claims/{claim_id}/status"
            )
            return

        d = decision_data["decision"]
        print()
        print(f"=== Result: claim {decision_data['claim_id']} (id={claim_id}) on {args.policy_number} ===")
        print(f"status:            {decision_data['status']}")
        print(f"fraud_score:       {d['fraud_score']}")
        print(f"escalation_flags:  {decision_data.get('escalation_flags')}")
        for m in decision_data.get("escalation_messages", []):
            print(f"  - {m}")
        print(f"reasoning:         {d['reasoning']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_find = sub.add_parser("find", help="List lakehouse policies by risk band/status (DB-direct, no app needed)")
    p_find.add_argument("--band", choices=["LOW", "MEDIUM", "HIGH"], help="Filter by claim_risk_band")
    p_find.add_argument("--active-only", action="store_true", help="Exclude policies with status=EXPIRED")
    p_find.add_argument("--limit", type=int, default=10)
    p_find.set_defaults(func=cmd_find)

    p_submit = sub.add_parser("submit", help="File + submit a full test claim against a running app instance")
    p_submit.add_argument("--policy-number", required=True)
    p_submit.add_argument("--email", help="Defaults to the policy's linked customer email")
    p_submit.add_argument("--password", default=DEFAULT_PASSWORD)
    p_submit.add_argument("--otp", default=DEFAULT_OTP)
    p_submit.add_argument("--base-url", default="http://127.0.0.1:8099")
    p_submit.add_argument("--claim-amount", type=float, default=45000.0)
    p_submit.add_argument("--incident-type", default="COLLISION")
    p_submit.add_argument("--incident-description", default="Rear-ended at a signal, bumper and tail light damaged.")
    p_submit.add_argument("--incident-datetime", default="2026-09-20T18:30:00")
    p_submit.add_argument("--location", default="Mumbai")
    p_submit.add_argument("--wait-seconds", type=int, default=30)
    p_submit.set_defaults(func=cmd_submit)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
