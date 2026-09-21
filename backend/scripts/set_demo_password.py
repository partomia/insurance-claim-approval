"""Testing utility: set/reset a known password for a demo user by email, for
any of the three portals (customer, agent, insurer).

Primary use case: policies/customers ingested by scripts/ingest_lakehouse.py
(Phase 3, LH-POL-* policies) get a placeholder hashed password with no known
plaintext — there's no real login flow for them. This script gives one of
those lakehouse customers a known password so a real claim can be submitted
against their policy through the normal UI/API flow, e.g. to test the
Phase 4 "Claim Insights" risk card (which only renders on a claim tied to a
policy that has a PolicyRiskSignal row).

NOT for production use — directly rewrites `hashed_password` in the live
DB with no auth/confirmation. Intended for local/CML demo databases only.

Usage:
    cd backend
    uv run python scripts/set_demo_password.py --role customer \\
        --email customer50@example.com --password password123
    uv run python scripts/set_demo_password.py --role agent --email ... --password ...
    uv run python scripts/set_demo_password.py --role insurer --email ... --password ...

    # List lakehouse-ingested customers to pick one (email + their policy numbers):
    uv run python scripts/set_demo_password.py --list-lakehouse-customers
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal  # noqa: E402
from dependencies import get_password_hash  # noqa: E402
from models.customer import Customer  # noqa: E402
from models.insurer_user import InsurerUser  # noqa: E402
from models.policy import Policy  # noqa: E402
from models.policy_agent import PolicyAgent  # noqa: E402

_MODELS = {
    "customer": Customer,
    "agent": PolicyAgent,
    "insurer": InsurerUser,
}


def list_lakehouse_customers(db) -> None:
    rows = (
        db.query(Customer, Policy)
        .join(Policy, Policy.customer_id == Customer.id)
        .filter(Policy.policy_number.like("LH-POL-%"))
        .order_by(Policy.policy_number)
        .all()
    )
    if not rows:
        print("No lakehouse (LH-POL-*) customers found — run 'bash cml/cli.sh lakehouse ingest' first.")
        return
    print(f"{'policy_number':<16} {'customer_email':<28} customer_name")
    for customer, policy in rows:
        print(f"{policy.policy_number:<16} {customer.email:<28} {customer.full_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", choices=sorted(_MODELS), help="customer | agent | insurer")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument(
        "--list-lakehouse-customers",
        action="store_true",
        help="List LH-POL-* policy owners (email + policy_number) instead of setting a password",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.list_lakehouse_customers:
            list_lakehouse_customers(db)
            return

        if not (args.role and args.email and args.password):
            parser.error("--role, --email, and --password are required (or use --list-lakehouse-customers)")

        model = _MODELS[args.role]
        user = db.query(model).filter(model.email == args.email).first()
        if not user:
            print(f"[error] No {args.role} found with email={args.email}", file=sys.stderr)
            sys.exit(1)
        user.hashed_password = get_password_hash(args.password)
        db.commit()
        print(f"[ok] Password reset for {args.role} {args.email} (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
