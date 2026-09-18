"""Phase 3 of the Cloudera datalakehouse story: pull the CDE-pipeline-produced
Iceberg gold tables (insurance_lakehouse.{policy_master,policy_clauses,
policy_risk_signals}) via Impala into the app's live SQLite database + Chroma
RAG index — so the running app's policy data actually originates from the
lakehouse pipeline (cde/README.md), not just provable via `lakehouse verify`.

Deliberately ADDITIVE, never destructive:
  - Does NOT touch the seed.py-generated demo policies (POL-MTR-100x) or
    their customer/claim data — those keep working exactly as before.
  - Lakehouse policies (LH-POL-*) are ingested under their own dedicated
    Customer accounts — one per policy_master row, created from its
    customer_name/customer_email — so they don't collide with the seeded
    demo customer.
  - Idempotent: matched/upserted by policy_number (Policy) and by
    (policy_id, title, section_ref) (PolicyDocument), so re-running after a
    fresh CDE pipeline run safely updates in place instead of duplicating.

Note: ingested customers get a placeholder password (see _LAKEHOUSE_PASSWORD
below) — there's no real login flow for them today; they exist so Policy's
NOT NULL customer_id FK is satisfiable and the data is inspectable via direct
DB queries / a future insurer-side "book of business" view. They are not
part of the seeded demo login (test@example.com).

Usage:
    uv run python scripts/ingest_lakehouse.py            # ingest + index into Chroma
    uv run python scripts/ingest_lakehouse.py --no-rag   # DB only, skip Chroma indexing
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from database import SessionLocal, _impala_connect  # noqa: E402
from db_init import ensure_schema  # noqa: E402
from dependencies import get_password_hash  # noqa: E402
import models  # noqa: E402,F401
from models.customer import Customer  # noqa: E402
from models.platform import InsuranceProvider  # noqa: E402
from models.policy import Policy, PolicyDocument, PolicyDocumentSource, PolicyStatus  # noqa: E402
from models.policy_risk_signal import PolicyRiskSignal  # noqa: E402
from services.rag_service import rag_service  # noqa: E402

settings = get_settings()

# Not a real credential — these customer accounts aren't reachable through
# the normal login flow's demo credentials; this just satisfies the
# NOT NULL/hashed_password column.
_LAKEHOUSE_PASSWORD_HASH = get_password_hash("lakehouse-pipeline-demo-not-a-real-login")


def db_name() -> str:
    return settings.lakehouse_database


def fetch_rows(cursor, table: str) -> list[dict]:
    cursor.execute(f"SELECT * FROM {db_name()}.{table}")
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def _parse_date(value) -> datetime:
    if value:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue
    return datetime.utcnow()


def upsert_provider(db, name: str | None) -> InsuranceProvider | None:
    if not name:
        return None
    provider = db.query(InsuranceProvider).filter(InsuranceProvider.name == name).first()
    if not provider:
        provider = InsuranceProvider(name=name, slug=_slugify(name), is_active=True)
        db.add(provider)
        db.flush()
    return provider


def upsert_customer(db, email: str, full_name: str) -> Customer:
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer:
        customer = Customer(
            email=email,
            full_name=full_name or email,
            hashed_password=_LAKEHOUSE_PASSWORD_HASH,
            gov_id_hash="lakehouse-pipeline-demo",
        )
        db.add(customer)
        db.flush()
    return customer


def upsert_policy(db, row: dict, provider: InsuranceProvider | None, customer: Customer) -> tuple[Policy, bool]:
    policy = db.query(Policy).filter(Policy.policy_number == row["policy_number"]).first()
    is_new = policy is None
    if is_new:
        policy = Policy(policy_number=row["policy_number"], customer_id=customer.id)
        db.add(policy)

    policy.customer_id = customer.id
    policy.provider_id = provider.id if provider else None
    policy.policy_type = row.get("policy_type") or "Motor"
    policy.premium_amount = float(row.get("premium_amount") or 0.0)
    try:
        policy.status = PolicyStatus(row.get("status") or "ACTIVE")
    except ValueError:
        policy.status = PolicyStatus.ACTIVE
    policy.coverage_limit = float(row.get("coverage_limit") or 0.0)
    policy.deductible = float(row.get("deductible") or 0.0)
    policy.co_pay_pct = float(row.get("co_pay_pct") or 0.0)
    policy.waiting_period_days = int(row.get("waiting_period_days") or 0)
    policy.effective_date = _parse_date(row.get("effective_date"))
    policy.expiry_date = _parse_date(row.get("expiry_date"))
    policy.depreciation_rate = float(row.get("depreciation_rate") or 0.0)
    policy.covered_vehicle_vin = row.get("covered_vehicle_vin")
    policy.covered_make = row.get("covered_make")
    policy.covered_model = row.get("covered_model")
    covered_year = row.get("covered_year")
    policy.covered_year = int(covered_year) if covered_year is not None else None
    policy.no_claim_bonus_pct = float(row.get("no_claim_bonus_pct") or 0.0)
    policy.zero_depreciation_addon = bool(row.get("zero_depreciation_addon"))
    policy.roadside_assistance_addon = bool(row.get("roadside_assistance_addon"))
    db.flush()
    return policy, is_new


def upsert_policy_document(db, policy: Policy, row: dict) -> tuple[PolicyDocument, bool]:
    doc = (
        db.query(PolicyDocument)
        .filter(
            PolicyDocument.policy_id == policy.id,
            PolicyDocument.title == row["title"],
            PolicyDocument.section_ref == row["section_ref"],
        )
        .first()
    )
    is_new = doc is None
    if is_new:
        doc = PolicyDocument(
            policy_id=policy.id,
            title=row["title"],
            section_ref=row["section_ref"],
            content_text=row["content_text"],
            source=PolicyDocumentSource.LAKEHOUSE,
        )
        db.add(doc)
    else:
        doc.content_text = row["content_text"]
    db.flush()
    return doc, is_new


def upsert_risk_signal(db, policy: Policy, row: dict) -> None:
    signal = db.query(PolicyRiskSignal).filter(PolicyRiskSignal.policy_id == policy.id).first()
    if not signal:
        signal = PolicyRiskSignal(policy_id=policy.id)
        db.add(signal)
    signal.total_claims_count = int(row.get("total_claims_count") or 0)
    signal.claims_count_12m = int(row.get("claims_count_12m") or 0)
    signal.total_claimed_amount = float(row.get("total_claimed_amount") or 0.0)
    signal.avg_claim_amount = float(row.get("avg_claim_amount") or 0.0)
    signal.amount_vs_segment_avg_pct = row.get("amount_vs_segment_avg_pct")
    signal.claim_frequency_percentile = row.get("claim_frequency_percentile")
    signal.linked_high_risk_garage = bool(row.get("linked_high_risk_garage"))
    signal.fraud_risk_score = float(row.get("fraud_risk_score") or 0.0)
    signal.claim_risk_band = row.get("claim_risk_band") or "LOW"
    signal.source = row.get("source") or "GOLD_PIPELINE"


def run(rag: bool = True) -> None:
    ensure_schema()  # make sure policy_risk_signals (new table) exists

    print(f"Connecting to Impala @ {settings.impala_host} (auth={settings.impala_auth_mechanism}) ...")
    conn = _impala_connect(database="default")
    cursor = conn.cursor()
    try:
        print(f"\n==> Reading {db_name()}.policy_master ...")
        policy_rows = fetch_rows(cursor, "policy_master")
        print(f"    {len(policy_rows)} rows")

        print(f"\n==> Reading {db_name()}.policy_clauses ...")
        clause_rows = fetch_rows(cursor, "policy_clauses")
        print(f"    {len(clause_rows)} rows")

        risk_rows: list[dict] = []
        try:
            print(f"\n==> Reading {db_name()}.policy_risk_signals ...")
            risk_rows = fetch_rows(cursor, "policy_risk_signals")
            print(f"    {len(risk_rows)} rows")
        except Exception as exc:  # noqa: BLE001
            print(
                f"    [warn] policy_risk_signals not available yet ({exc}) — "
                f"skipping risk-signal ingest (run the CDE claims-analytics "
                f"pipeline first, see cde/README.md)"
            )
    finally:
        cursor.close()
        conn.close()

    if not policy_rows:
        print("\nNo rows in policy_master — nothing to ingest. Run `cml/cli.sh lakehouse seed` "
              "or the CDE pipeline first.")
        return

    risk_by_policy_number = {r["policy_number"]: r for r in risk_rows}
    clauses_by_policy_number: dict[str, list[dict]] = {}
    for row in clause_rows:
        clauses_by_policy_number.setdefault(row["policy_number"], []).append(row)

    db = SessionLocal()
    new_policies = updated_policies = new_documents = risk_signals_ingested = rag_chunks_indexed = 0
    try:
        for row in policy_rows:
            provider = upsert_provider(db, row.get("provider_name"))
            customer = upsert_customer(db, row["customer_email"], row.get("customer_name") or row["customer_email"])
            policy, is_new = upsert_policy(db, row, provider, customer)
            new_policies += int(is_new)
            updated_policies += int(not is_new)

            for clause_row in clauses_by_policy_number.get(row["policy_number"], []):
                doc, doc_is_new = upsert_policy_document(db, policy, clause_row)
                new_documents += int(doc_is_new)
                if rag and doc.content_text:
                    rag_chunks_indexed += rag_service.index_policy_document(
                        db,
                        policy.id,
                        doc.content_text,
                        section_ref=doc.section_ref,
                        source="lakehouse",
                        filename=doc.title,
                        document_id=doc.id,
                    )

            risk_row = risk_by_policy_number.get(row["policy_number"])
            if risk_row:
                upsert_risk_signal(db, policy, risk_row)
                risk_signals_ingested += 1

        db.commit()
    finally:
        db.close()

    print("\n==> Ingest complete:")
    print(
        f"    Policies:      {new_policies} new, {updated_policies} updated "
        f"({len(policy_rows)} total from lakehouse)"
    )
    print(f"    Documents:     {new_documents} new policy clauses")
    print(f"    Risk signals:  {risk_signals_ingested} policies matched in policy_risk_signals")
    if rag:
        print(f"    RAG:           {rag_chunks_indexed} chunks indexed into Chroma")
        print(f"    Chroma total:  {rag_service.count()} vectors")
    else:
        print("    RAG:           skipped (--no-rag)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-rag", action="store_true", help="Skip Chroma/RAG indexing (DB only)")
    args = parser.parse_args()
    run(rag=not args.no_rag)
