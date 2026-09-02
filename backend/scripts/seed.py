"""Seed the demo database with motor-only data.

Creates one demo customer, three motor policies (each covering a distinct vehicle),
motor policy documents + RAG clauses, two demo motor-claim experts, and an insurer
back-office user.
"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from passlib.context import CryptContext

from db_init import ensure_schema
from database import SessionLocal
from dependencies import get_password_hash
import models  # noqa: F401
from models.claim import Claim, ClaimStatus
from models.customer import Customer
from models.policy import (
    Policy,
    PolicyDocument,
    PolicyDocumentSource,
    PolicyStatus,
    PremiumPayment,
    PremiumPaymentStatus,
)
from models.policy_agent import PolicyAgent
from models.platform import CustomerProfile, InsuranceProvider, KYCStatus
from services.rag_service import rag_service

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Motor-only insurers.
INSURANCE_PROVIDERS = [
    ("Bajaj Allianz Motor", "bajaj-allianz-motor"),
    ("ICICI Lombard Motor", "icici-lombard-motor"),
    ("HDFC ERGO Motor", "hdfc-ergo-motor"),
    ("Acko Drive", "acko-drive"),
    ("Tata AIG Motor", "tata-aig-motor"),
    ("Reliance General Motor", "reliance-general-motor"),
]

# One shared motor policy schedule template applied to every seeded policy.
MOTOR_POLICY_SCHEDULE = [
    (
        "Policy Schedule",
        "Section 1.0",
        "This Motor Comprehensive Policy provides own-damage and third-party liability "
        "coverage for the insured private vehicle for a period of 12 months from the "
        "effective date. Insured Declared Value (IDV) is the maximum settlement amount "
        "for total loss.",
    ),
    (
        "Coverage Details",
        "Section 4.2",
        "Own-damage coverage includes collision, theft, fire, vandalism, natural disasters, "
        "and glass breakage. Third-party liability covers bodily injury and property "
        "damage to third parties as required by law. Add-ons available: zero-depreciation, "
        "roadside assistance, engine protection, consumables cover.",
    ),
    (
        "Exclusions",
        "Section 7.1",
        "Exclusions: driving under influence of alcohol or drugs, driving without a "
        "valid licence, racing or speed testing, commercial use without endorsement, "
        "consequential loss, mechanical/electrical breakdown, wear and tear, and "
        "damage caused by war or nuclear risks.",
    ),
    (
        "Add-ons",
        "Section 5.0",
        "Zero-depreciation add-on waives depreciation on plastic and rubber parts. "
        "Roadside assistance covers towing up to 100 km. No-Claim Bonus (NCB) grows "
        "each claim-free year up to 50%.",
    ),
    (
        "Claim Settlement",
        "Section 3.5",
        "Deductible of $500 applies per own-damage claim. Depreciation applied per "
        "vehicle age schedule unless zero-dep add-on is active. Cashless settlement "
        "available at network garages. Repair cost above 75% of IDV is treated as "
        "total loss and settled at IDV minus salvage.",
    ),
]

# RAG clause corpus — one per policy_id slot; all motor.
MOTOR_CLAUSES_TEMPLATE = [
    {
        "section_ref": "Section 4.2",
        "clause_text": (
            "Own-damage coverage includes collision, theft, fire, vandalism, natural "
            "disasters, and glass breakage up to the Insured Declared Value (IDV)."
        ),
        "embedding_metadata": {"category": "coverage"},
    },
    {
        "section_ref": "Section 4.3",
        "clause_text": (
            "Third-party liability coverage indemnifies the insured against bodily "
            "injury and property damage to third parties as mandated by the Motor "
            "Vehicles Act."
        ),
        "embedding_metadata": {"category": "coverage"},
    },
    {
        "section_ref": "Section 7.1",
        "clause_text": (
            "Exclusions: driving under influence, unlicensed driver, racing, "
            "commercial use without endorsement, and consequential loss."
        ),
        "embedding_metadata": {"category": "exclusion"},
    },
    {
        "section_ref": "Section 5.0",
        "clause_text": (
            "Zero-depreciation add-on waives depreciation on plastic and rubber parts. "
            "No-Claim Bonus (NCB) grows each claim-free year up to 50%."
        ),
        "embedding_metadata": {"category": "add-on"},
    },
    {
        "section_ref": "Section 3.5",
        "clause_text": (
            "Deductible of $500 applies per claim. Repair cost above 75% of IDV is "
            "treated as total loss and settled at IDV minus salvage."
        ),
        "embedding_metadata": {"category": "settlement"},
    },
]


def seed_db(reset: bool = False) -> None:
    ensure_schema(force_reset=reset)
    db = SessionLocal()
    try:
        for name, slug in INSURANCE_PROVIDERS:
            if not db.query(InsuranceProvider).filter(InsuranceProvider.slug == slug).first():
                db.add(InsuranceProvider(name=name, slug=slug, is_active=True))
        db.commit()

        customer = db.query(Customer).filter(Customer.email == "test@example.com").first()
        if not customer:
            customer = Customer(
                email="test@example.com",
                full_name="Test User",
                hashed_password=get_password_hash("password123"),
                gov_id_hash="gov-id-hash-demo",
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)

        profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer.id).first()
        if not profile:
            profile = CustomerProfile(
                customer_id=customer.id,
                phone="9876543210",
                kyc_status=KYCStatus.PENDING,
                saved_vehicles=[
                    {
                        "make": "Toyota",
                        "model": "Camry",
                        "year": 2022,
                        "vin": "1HGBH41JXMN109186",
                        "license_plate": "MH-01-AB-1234",
                    }
                ],
                saved_garages=[
                    {"name": "Prime Auto Body Shop", "city": "Mumbai"},
                ],
            )
            db.add(profile)
            db.commit()
        elif profile.kyc_gov_id_path and not Path(profile.kyc_gov_id_path).is_file():
            profile.kyc_gov_id_path = None
            profile.kyc_face_verified = False
            profile.kyc_mobile_verified = False
            profile.kyc_status = KYCStatus.PENDING
            profile.kyc_verified_at = None
            db.commit()

        now = datetime.utcnow()
        # Motor policies — each covering a distinct vehicle.
        policies_data = [
            {
                "policy_number": "POL-MTR-1001",
                "coverage_limit": 500000.0,
                "deductible": 500.0,
                "co_pay_pct": 0.0,
                "exclusions": ["unlicensed driver", "racing", "commercial use"],
                "depreciation_rate": 5.0,
                "covered_make": "Toyota",
                "covered_model": "Camry",
                "covered_year": 2022,
                "covered_vehicle_vin": "1HGBH41JXMN109186",
                "no_claim_bonus_pct": 20.0,
                "zero_depreciation_addon": True,
                "roadside_assistance_addon": True,
            },
            {
                "policy_number": "POL-MTR-1002",
                "coverage_limit": 300000.0,
                "deductible": 750.0,
                "co_pay_pct": 5.0,
                "exclusions": ["unlicensed driver", "racing"],
                "depreciation_rate": 10.0,
                "covered_make": "Honda",
                "covered_model": "Civic",
                "covered_year": 2019,
                "covered_vehicle_vin": "2HGFC2F59KH500001",
                "no_claim_bonus_pct": 35.0,
                "zero_depreciation_addon": False,
                "roadside_assistance_addon": True,
            },
            {
                "policy_number": "POL-MTR-1003",
                "coverage_limit": 800000.0,
                "deductible": 1000.0,
                "co_pay_pct": 0.0,
                "exclusions": ["unlicensed driver", "DUI", "racing", "commercial use"],
                "depreciation_rate": 5.0,
                "covered_make": "BMW",
                "covered_model": "3 Series",
                "covered_year": 2023,
                "covered_vehicle_vin": "WBA5A5C58DD000001",
                "no_claim_bonus_pct": 0.0,
                "zero_depreciation_addon": True,
                "roadside_assistance_addon": True,
            },
        ]

        policy_ids: list[int] = []
        for pdata in policies_data:
            policy = db.query(Policy).filter(Policy.policy_number == pdata["policy_number"]).first()
            if not policy:
                policy = Policy(
                    policy_number=pdata["policy_number"],
                    customer_id=customer.id,
                    policy_type="Motor",
                    status=PolicyStatus.ACTIVE,
                    coverage_limit=pdata["coverage_limit"],
                    deductible=pdata["deductible"],
                    co_pay_pct=pdata["co_pay_pct"],
                    exclusions=pdata["exclusions"],
                    waiting_period_days=0,
                    effective_date=now - timedelta(days=365),
                    expiry_date=now + timedelta(days=365),
                    depreciation_rate=pdata["depreciation_rate"],
                    covered_make=pdata["covered_make"],
                    covered_model=pdata["covered_model"],
                    covered_year=pdata["covered_year"],
                    covered_vehicle_vin=pdata["covered_vehicle_vin"],
                    no_claim_bonus_pct=pdata["no_claim_bonus_pct"],
                    zero_depreciation_addon=pdata["zero_depreciation_addon"],
                    roadside_assistance_addon=pdata["roadside_assistance_addon"],
                )
                db.add(policy)
                db.commit()
                db.refresh(policy)

                payment = PremiumPayment(
                    policy_id=policy.id,
                    amount=1200.0,
                    paid_at=now - timedelta(days=30),
                    status=PremiumPaymentStatus.PAID,
                )
                db.add(payment)
                db.commit()
            policy_ids.append(policy.id)

        for policy in db.query(Policy).all():
            if db.query(PolicyDocument).filter(PolicyDocument.policy_id == policy.id).count() == 0:
                for title, section_ref, content in MOTOR_POLICY_SCHEDULE:
                    db.add(
                        PolicyDocument(
                            policy_id=policy.id,
                            title=title,
                            section_ref=section_ref,
                            content_text=content,
                            source=PolicyDocumentSource.SEED,
                        )
                    )
                db.commit()

        # Build the RAG corpus: one set of motor clauses per policy.
        clauses_with_ids = []
        for pid in policy_ids:
            for clause in MOTOR_CLAUSES_TEMPLATE:
                clauses_with_ids.append({**clause, "policy_id": pid})

        if rag_service.count() == 0:
            rag_service.ingest_clauses(db, clauses_with_ids, rebuild=True)
            for policy in db.query(Policy).all():
                for doc in db.query(PolicyDocument).filter(PolicyDocument.policy_id == policy.id).all():
                    if doc.content_text:
                        rag_service.index_policy_document(
                            db,
                            policy.id,
                            doc.content_text,
                            section_ref=doc.section_ref,
                            source="seed",
                            filename=doc.title,
                            document_id=doc.id,
                        )

        demo_agents = [
            {
                "email": "expert1@claimcopilot.in",
                "full_name": "Ananya Desai",
                "password": "password123",
                "department": "Senior Motor Claims Advisor",
            },
            {
                "email": "expert2@claimcopilot.in",
                "full_name": "Rohit Mehta",
                "password": "password123",
                "department": "Motor Fraud Investigator",
            },
        ]
        for agent_data in demo_agents:
            agent = db.query(PolicyAgent).filter(PolicyAgent.email == agent_data["email"]).first()
            if not agent:
                agent = PolicyAgent(
                    email=agent_data["email"],
                    full_name=agent_data["full_name"],
                    hashed_password=get_password_hash(agent_data["password"]),
                    department=agent_data["department"],
                )
                db.add(agent)
                db.commit()
                db.refresh(agent)

        from models.insurer_user import InsurerUser

        demo_insurer = db.query(InsurerUser).filter(InsurerUser.email == "insurer1@claimcopilot.in").first()
        if not demo_insurer:
            demo_insurer = InsurerUser(
                email="insurer1@claimcopilot.in",
                full_name="Rajesh Iyer",
                hashed_password=get_password_hash("password123"),
                department="Senior Motor Claims Adjuster",
            )
            db.add(demo_insurer)
            db.commit()

        for claim in db.query(Claim).filter(Claim.assigned_agent.isnot(None)).all():
            if claim.assigned_agent_id:
                continue
            agent = (
                db.query(PolicyAgent)
                .filter(
                    (PolicyAgent.email == claim.assigned_agent)
                    | (PolicyAgent.full_name == claim.assigned_agent)
                )
                .first()
            )
            if agent:
                claim.assigned_agent_id = agent.id
        db.commit()

        expert1 = db.query(PolicyAgent).filter(PolicyAgent.email == "expert1@claimcopilot.in").first()
        if expert1:
            from services.expert_queue_service import backfill_unassigned_queue_claims

            backfill_unassigned_queue_claims(db)

        test_customer = db.query(Customer).filter(Customer.email == "test@example.com").first()
        if expert1 and test_customer:
            demo_statuses = (ClaimStatus.ANALYSIS_COMPLETE, ClaimStatus.PENDING_REVIEW)
            for claim in (
                db.query(Claim)
                .filter(
                    Claim.customer_id == test_customer.id,
                    Claim.status.in_(demo_statuses),
                    Claim.assigned_agent_id.is_(None),
                )
                .all()
            ):
                claim.assigned_agent_id = expert1.id
                claim.assigned_agent = expert1.full_name
                claim.assigned_at = datetime.utcnow()
            db.commit()

        print("Database seeded with motor customer, 3 motor policies, and Chroma index.")
        print("Run `python backend/scripts/seed_enterprise.py --reset` for full enterprise demo data.")
        print("  Demo insurer: insurer1@claimcopilot.in / password123 / OTP 112233")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables")
    args = parser.parse_args()
    seed_db(reset=args.reset)
