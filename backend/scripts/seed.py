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

INSURANCE_PROVIDERS = [
    ("HDFC Ergo", "hdfc-ergo"),
    ("ICICI Lombard", "icici-lombard"),
    ("Bajaj Allianz", "bajaj-allianz"),
    ("Star Health", "star-health"),
    ("Care Insurance", "care-insurance"),
    ("Niva Bupa", "niva-bupa"),
    ("Acko", "acko"),
    ("Tata AIG", "tata-aig"),
]

POLICY_SCHEDULE_DOCS = {
    "Auto": [
        ("Policy Schedule", "Section 1.0", "This Auto Comprehensive Policy provides coverage for owned vehicles used for personal transportation. Policy period is 12 months from effective date."),
        ("Coverage Details", "Section 4.2", "Comprehensive coverage includes collision, theft, fire, vandalism, and natural disasters up to the stated coverage limit of the insured vehicle."),
        ("Exclusions", "Section 7.1", "Exclusions: intentional damage, racing, unlicensed operation, commercial use without rider, and damage while driver is under influence."),
        ("Settlement", "Section 3.5", "Deductible of $500 applies per claim. Co-pay of 10% applies after deductible. Depreciation of 5% per year on vehicle parts."),
    ],
    "Health": [
        ("Policy Schedule", "Section 1.0", "This Health Insurance Policy covers hospitalization, surgery, and prescription drugs for the insured and dependents."),
        ("Coverage Details", "Section 2.1", "In-patient hospitalization, day-care procedures, ambulance charges, and post-hospitalization expenses are covered up to sum insured."),
        ("Exclusions", "Section 5.3", "Cosmetic surgery, experimental treatments, self-inflicted injuries, and pre-existing conditions within waiting period are excluded."),
        ("Settlement", "Section 3.2", "Deductible of $1,000 per policy year. Co-pay of 20% on all approved claims after deductible."),
    ],
    "Home": [
        ("Policy Schedule", "Section 1.0", "This Home Insurance Policy covers the structure and contents of the insured residential property."),
        ("Coverage Details", "Section 1.4", "Fire, theft, windstorm, lightning, and explosion damage to building and contents are covered."),
        ("Exclusions", "Section 6.1", "Flood, earthquake (unless rider purchased), wear and tear, and unoccupied property over 60 days are excluded."),
        ("Settlement", "Section 2.3", "Deductible of $2,000 per claim. Depreciation of 10% on building contents over 5 years old."),
    ],
}

MOCK_CLAUSES = [
    {
        "policy_id": 1,
        "section_ref": "Section 4.2",
        "clause_text": "Comprehensive coverage includes collision, theft, and natural disasters up to policy limits.",
        "embedding_metadata": {"category": "coverage"},
    },
    {
        "policy_id": 1,
        "section_ref": "Section 7.1",
        "clause_text": "Exclusions: intentional damage, racing, and unlicensed operation are not covered.",
        "embedding_metadata": {"category": "exclusion"},
    },
    {
        "policy_id": 1,
        "section_ref": "Section 3.5",
        "clause_text": "Deductible of $500 applies per claim. Co-pay of 10% applies after deductible.",
        "embedding_metadata": {"category": "settlement"},
    },
    {
        "policy_id": 2,
        "section_ref": "Section 2.1",
        "clause_text": "Health coverage includes hospitalization, surgery, and prescription drugs.",
        "embedding_metadata": {"category": "coverage"},
    },
    {
        "policy_id": 2,
        "section_ref": "Section 5.3",
        "clause_text": "Cosmetic surgery and experimental treatments are excluded from coverage.",
        "embedding_metadata": {"category": "exclusion"},
    },
    {
        "policy_id": 3,
        "section_ref": "Section 1.4",
        "clause_text": "Home coverage includes fire, theft, and windstorm damage to insured property.",
        "embedding_metadata": {"category": "coverage"},
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
            )
            db.add(profile)
            db.commit()
        elif profile.kyc_gov_id_path and not Path(profile.kyc_gov_id_path).is_file():
            # Clear demo seed flags when no real ID file was uploaded
            profile.kyc_gov_id_path = None
            profile.kyc_face_verified = False
            profile.kyc_mobile_verified = False
            profile.kyc_status = KYCStatus.PENDING
            profile.kyc_verified_at = None
            db.commit()

        now = datetime.utcnow()
        policies_data = [
            {
                "policy_number": "POL-12345",
                "policy_type": "Auto",
                "coverage_limit": 500000.0,
                "deductible": 500.0,
                "co_pay_pct": 10.0,
                "exclusions": ["intentional damage", "racing"],
                "depreciation_rate": 5.0,
            },
            {
                "policy_number": "POL-67890",
                "policy_type": "Health",
                "coverage_limit": 1000000.0,
                "deductible": 1000.0,
                "co_pay_pct": 20.0,
                "exclusions": ["cosmetic surgery", "experimental treatments"],
                "depreciation_rate": 0.0,
            },
            {
                "policy_number": "POL-11111",
                "policy_type": "Home",
                "coverage_limit": 300000.0,
                "deductible": 2000.0,
                "co_pay_pct": 0.0,
                "exclusions": ["flood", "earthquake"],
                "depreciation_rate": 10.0,
            },
        ]

        policy_ids: list[int] = []
        for pdata in policies_data:
            policy = db.query(Policy).filter(Policy.policy_number == pdata["policy_number"]).first()
            if not policy:
                policy = Policy(
                    policy_number=pdata["policy_number"],
                    customer_id=customer.id,
                    policy_type=pdata["policy_type"],
                    status=PolicyStatus.ACTIVE,
                    coverage_limit=pdata["coverage_limit"],
                    deductible=pdata["deductible"],
                    co_pay_pct=pdata["co_pay_pct"],
                    exclusions=pdata["exclusions"],
                    waiting_period_days=0,
                    effective_date=now - timedelta(days=365),
                    expiry_date=now + timedelta(days=365),
                    depreciation_rate=pdata["depreciation_rate"],
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
                schedule = POLICY_SCHEDULE_DOCS.get(policy.policy_type, POLICY_SCHEDULE_DOCS["Auto"])
                for title, section_ref, content in schedule:
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

        clauses_with_ids = []
        for i, clause in enumerate(MOCK_CLAUSES):
            pid = policy_ids[min(i // 2, len(policy_ids) - 1)]
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
                "department": "Senior Claim Consultant",
            },
            {
                "email": "expert2@claimcopilot.in",
                "full_name": "Rohit Mehta",
                "password": "password123",
                "department": "Health Claims Advisor",
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
                department="Senior Claims Adjuster",
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

        if test_customer:
            submitted_demo = (
                db.query(Claim)
                .filter(Claim.customer_id == test_customer.id)
                .order_by(Claim.updated_at.desc())
                .first()
            )
            if submitted_demo and expert1:
                submitted_demo.status = ClaimStatus.SUBMITTED_TO_INSURER
                submitted_demo.assigned_agent_id = expert1.id
                submitted_demo.assigned_agent = expert1.full_name
                db.commit()

        print("Database seeded with customer, policies, demo agents, and Chroma index.")
        print("Run `python backend/scripts/seed_enterprise.py --reset` for full enterprise demo data.")
        print("  Demo insurer: insurer1@claimcopilot.in / password123 / OTP 112233")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables")
    args = parser.parse_args()
    seed_db(reset=args.reset)
