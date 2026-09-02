"""Enterprise seed data: 30 customers, 100 claims, providers, experts."""

import argparse
import random
import uuid
from datetime import datetime, timedelta

from db_init import ensure_schema
from database import SessionLocal
from dependencies import get_password_hash
import models  # noqa: F401
from models.audit import ClaimDecision, FraudAssessment, HumanReview, HumanReviewStatus
from models.claim import Claim, ClaimStatus, DocumentType
from models.customer import Customer
from models.platform import CustomerProfile, InsuranceProvider, KYCStatus
from models.policy import Policy, PolicyDocument, PolicyDocumentSource, PolicyStatus, PremiumPayment, PremiumPaymentStatus
from models.policy_agent import PolicyAgent
from services.analysis_service import compute_analysis_fields

PROVIDERS = [
    ("Bajaj Allianz Motor", "bajaj-allianz-motor"),
    ("ICICI Lombard Motor", "icici-lombard-motor"),
    ("HDFC ERGO Motor", "hdfc-ergo-motor"),
    ("Acko Drive", "acko-drive"),
    ("Tata AIG Motor", "tata-aig-motor"),
    ("Reliance General Motor", "reliance-general-motor"),
]

FIRST_NAMES = [
    "Priya", "Rahul", "Ananya", "Vikram", "Sneha", "Arjun", "Kavita", "Rohan",
    "Meera", "Aditya", "Divya", "Karan", "Neha", "Sanjay", "Pooja", "Amit",
    "Lakshmi", "Deepak", "Shreya", "Manish", "Nisha", "Rajesh", "Anjali", "Suresh",
    "Kritika", "Harish", "Tanvi", "Gaurav", "Isha", "Naveen",
]

LAST_NAMES = [
    "Sharma", "Patel", "Reddy", "Iyer", "Gupta", "Singh", "Nair", "Mehta",
    "Joshi", "Desai", "Kapoor", "Malhotra", "Verma", "Chopra", "Rao", "Pillai",
]

GARAGES = [
    {"name": "MyTVS Auto", "city": "Bangalore"},
    {"name": "Bosch Car Service", "city": "Pune"},
    {"name": "Mahindra First Choice", "city": "Hyderabad"},
    {"name": "Prime Auto Body Shop", "city": "Mumbai"},
    {"name": "Denting & Painting Co.", "city": "Delhi"},
]

VEHICLES = [
    {"make": "Maruti", "model": "Swift", "year": 2021, "vin": "MA3ETDE1S00500001"},
    {"make": "Hyundai", "model": "Creta", "year": 2022, "vin": "MALA751CLNM500001"},
    {"make": "Honda", "model": "City", "year": 2020, "vin": "JHMCB7660LC500001"},
    {"make": "Tata", "model": "Nexon", "year": 2023, "vin": "MAT625134PPT00001"},
    {"make": "Toyota", "model": "Innova", "year": 2019, "vin": "MHFAX8G80K1500001"},
]

INCIDENTS = {
    "Motor": [
        "Rear-end collision damage repair",
        "Windshield replacement after stone chip",
        "Theft of vehicle accessories overnight",
        "Flood damage to engine after monsoon flooding",
        "Side mirror damage in parking lot hit-and-run",
        "T-bone collision at intersection",
        "Vandalism — paint scratches across side panel",
        "Fire damage after electrical short",
        "Front bumper and headlight damage after hitting divider",
        "Total loss after highway collision with truck",
    ],
}

POLICY_TYPES = ["Motor"]
STATUSES = [
    ClaimStatus.ANALYSIS_COMPLETE,
    ClaimStatus.PENDING_REVIEW,
    ClaimStatus.SUBMISSION_READY,
    ClaimStatus.SUBMITTED_TO_INSURER,
    ClaimStatus.REQUEST_MORE_INFO,
    ClaimStatus.APPROVED,
    ClaimStatus.REJECTED,
    ClaimStatus.DRAFT,
]

PROBLEMS = [
    "Repair estimate not signed by garage",
    "Damage photos do not match the described incident",
    "Claim amount exceeds declared IDV",
    "FIR copy not uploaded for a third-party incident",
    "VIN on claim does not match policy's covered vehicle",
    "Driver's licence expired at the time of incident",
]

RECOMMENDATIONS = [
    "Upload the garage's original itemized repair estimate",
    "Use a signed original invoice, not a photocopy",
    "Add clear geo-tagged photos of all damaged panels",
    "Include the VIN/chassis plate photo",
    "Upload the police FIR for third-party incidents",
]


def seed_enterprise(reset: bool = False) -> None:
    ensure_schema(force_reset=reset)
    db = SessionLocal()
    random.seed(42)
    now = datetime.utcnow()

    try:
        provider_map: dict[str, InsuranceProvider] = {}
        for name, slug in PROVIDERS:
            p = db.query(InsuranceProvider).filter(InsuranceProvider.slug == slug).first()
            if not p:
                p = InsuranceProvider(name=name, slug=slug, is_active=True)
                db.add(p)
                db.commit()
                db.refresh(p)
            provider_map[slug] = p

        experts_data = [
            ("expert1@claimcopilot.in", "Ananya Desai", "Senior Claim Consultant"),
            ("expert2@claimcopilot.in", "Rohit Mehta", "Motor Fraud Investigator"),
            ("expert3@claimcopilot.in", "Kavita Nair", "Motor Claims Specialist"),
            ("expert4@claimcopilot.in", "Vikram Singh", "Policy Coverage Expert"),
        ]
        experts: list[PolicyAgent] = []
        for email, name, dept in experts_data:
            agent = db.query(PolicyAgent).filter(PolicyAgent.email == email).first()
            if not agent:
                agent = PolicyAgent(
                    email=email,
                    full_name=name,
                    hashed_password=get_password_hash("password123"),
                    department=dept,
                )
                db.add(agent)
                db.commit()
                db.refresh(agent)
            experts.append(agent)

        from models.insurer_user import InsurerUser

        insurer = db.query(InsurerUser).filter(InsurerUser.email == "insurer1@claimcopilot.in").first()
        if not insurer:
            insurer = InsurerUser(
                email="insurer1@claimcopilot.in",
                full_name="Rajesh Iyer",
                hashed_password=get_password_hash("password123"),
                department="Senior Claims Adjuster",
            )
            db.add(insurer)
            db.commit()

        customers: list[Customer] = []
        for i in range(30):
            first = FIRST_NAMES[i]
            last = LAST_NAMES[i % len(LAST_NAMES)]
            email = "priya.sharma@example.com" if i == 0 else f"{first.lower()}.{last.lower()}{i}@example.com"
            customer = db.query(Customer).filter(Customer.email == email).first()
            if not customer:
                customer = Customer(
                    email=email,
                    full_name=f"{first} {last}",
                    hashed_password=get_password_hash("password123"),
                    gov_id_hash=f"aadhaar-hash-{i}",
                )
                db.add(customer)
                db.commit()
                db.refresh(customer)

            profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer.id).first()
            if not profile:
                dob = now - timedelta(days=365 * random.randint(25, 55))
                profile = CustomerProfile(
                    customer_id=customer.id,
                    phone=f"98{random.randint(10000000, 99999999)}",
                    date_of_birth=dob,
                    kyc_status=KYCStatus.VERIFIED if i < 28 else KYCStatus.PENDING,
                    kyc_gov_id_path=f"/uploads/kyc/{customer.id}/aadhaar.pdf" if i < 28 else None,
                    kyc_face_verified=i < 28,
                    kyc_mobile_verified=i < 28,
                    kyc_verified_at=now - timedelta(days=random.randint(30, 400)) if i < 28 else None,
                    emergency_contacts=[{"name": f"{last} Family", "phone": "9876543210", "relation": "Spouse"}],
                    saved_vehicles=random.sample(VEHICLES, k=random.randint(1, 2)),
                    saved_garages=random.sample(GARAGES, k=random.randint(1, 3)),
                    preferred_providers=random.sample([s for _, s in PROVIDERS], k=3),
                    dependents=[{"name": f"Child {first}", "age": random.randint(5, 18), "relation": "Child"}],
                    risk_profile={"tier": random.choice(["low", "medium", "high"]), "prior_rejections": random.randint(0, 2)},
                )
                db.add(profile)
                db.commit()

            customers.append(customer)

        policy_ids: list[int] = []
        for i, customer in enumerate(customers):
            if db.query(Policy).filter(Policy.customer_id == customer.id).count() >= 1:
                existing = db.query(Policy).filter(Policy.customer_id == customer.id).all()
                policy_ids.extend(p.id for p in existing)
                continue

            for j in range(random.randint(1, 2)):
                ptype = "Motor"
                provider = random.choice(list(provider_map.values()))
                policy_number = f"{provider.slug[:3].upper()}-MTR-{customer.id:03d}-{j+1}"
                effective = now - timedelta(days=random.randint(180, 900))
                covered_vehicle = random.choice(VEHICLES)
                policy = Policy(
                    policy_number=policy_number,
                    customer_id=customer.id,
                    provider_id=provider.id,
                    policy_type=ptype,
                    status=PolicyStatus.ACTIVE,
                    coverage_limit=random.choice([300000, 500000, 800000, 1000000]),
                    deductible=random.choice([500, 750, 1000, 2000]),
                    co_pay_pct=0.0,
                    exclusions=["unlicensed driver", "racing", "commercial use"],
                    waiting_period_days=0,
                    effective_date=effective,
                    expiry_date=effective + timedelta(days=365),
                    depreciation_rate=5.0,
                    premium_amount=12400,
                    covered_make=covered_vehicle["make"],
                    covered_model=covered_vehicle["model"],
                    covered_year=covered_vehicle["year"],
                    covered_vehicle_vin=covered_vehicle["vin"],
                    no_claim_bonus_pct=random.choice([0.0, 20.0, 25.0, 35.0, 50.0]),
                    zero_depreciation_addon=random.random() < 0.4,
                    roadside_assistance_addon=random.random() < 0.6,
                )
                db.add(policy)
                db.commit()
                db.refresh(policy)
                policy_ids.append(policy.id)

                for months_ago in range(0, 24, 12):
                    db.add(
                        PremiumPayment(
                            policy_id=policy.id,
                            amount=policy.premium_amount,
                            paid_at=now - timedelta(days=30 * months_ago),
                            status=PremiumPaymentStatus.PAID,
                        )
                    )
                db.add(
                    PolicyDocument(
                        policy_id=policy.id,
                        title="Policy Schedule",
                        section_ref="Section 1.0",
                        content_text=f"{ptype} policy schedule for {provider.name}. Coverage and exclusions apply.",
                        source=PolicyDocumentSource.SEED,
                    )
                )
                db.commit()

        existing_claims = db.query(Claim).count()
        claims_to_create = max(0, 100 - existing_claims)
        for n in range(claims_to_create):
            customer = random.choice(customers)
            policies = db.query(Policy).filter(Policy.customer_id == customer.id).all()
            if not policies:
                continue
            policy = random.choice(policies)
            ptype = policy.policy_type
            status = random.choice(STATUSES)
            amount = round(random.uniform(5000, 250000), 2)
            incident = random.choice(INCIDENTS["Motor"])
            claim_number = f"CLM{uuid.uuid4().hex[:8].upper()}"

            claim = Claim(
                claim_number=claim_number,
                customer_id=customer.id,
                policy_id=policy.id,
                incident_description=incident,
                incident_datetime=now - timedelta(days=random.randint(1, 180)),
                location=random.choice(["Mumbai", "Delhi", "Bangalore", "Chennai", "Pune", "Hyderabad"]),
                claim_amount=amount,
                status=status,
                submission_step=4 if status != ClaimStatus.DRAFT else random.randint(1, 3),
                policy_context_json={"coverage_summary": f"{ptype} coverage applies to described incident."},
                escalation_flags=random.sample(["missing_documents", "clause_mismatch", "high_fraud_risk"], k=random.randint(0, 2)),
                assigned_agent_id=random.choice(experts).id if status in (ClaimStatus.PENDING_REVIEW, ClaimStatus.SUBMISSION_READY) else None,
                assigned_agent=random.choice(experts).full_name if status in (ClaimStatus.PENDING_REVIEW, ClaimStatus.SUBMISSION_READY) else None,
                assigned_at=now - timedelta(days=random.randint(1, 14)) if status in (ClaimStatus.PENDING_REVIEW, ClaimStatus.SUBMISSION_READY) else None,
            )
            db.add(claim)
            db.commit()
            db.refresh(claim)

            if status == ClaimStatus.DRAFT:
                continue

            fraud_score = round(random.uniform(0.05, 0.65), 3)
            confidence = round(random.uniform(0.55, 0.98), 3)
            payable = round(amount * random.uniform(0.6, 0.95), 2) if status not in (ClaimStatus.REJECTED, ClaimStatus.DRAFT) else 0

            db.add(
                FraudAssessment(
                    claim_id=claim.id,
                    fraud_score=fraud_score,
                    signals=[{"signal": "duplicate_claim_pattern", "weight": fraud_score}] if fraud_score > 0.4 else [],
                    blacklist_hit=False,
                )
            )

            decision = ClaimDecision(
                claim_id=claim.id,
                status=status,
                payable_amount=payable,
                confidence_score=confidence,
                reasoning=f"AI analyzed {ptype.lower()} claim against {policy.provider.name if policy.provider else 'policy'} terms.",
                retrieved_clauses=[{"section_ref": "Section 2.1", "clause_text": "Coverage for eligible incidents per policy schedule."}],
                evidence_results=[{"doc_type": "INVOICE", "valid": random.choice([True, False]), "confidence": confidence}],
                fraud_score=fraud_score,
                human_review_required=status in (ClaimStatus.PENDING_REVIEW, ClaimStatus.HUMAN_REVIEW),
                payout_breakdown={"gross": amount, "deductible": policy.deductible, "payable": payable},
                potential_problems=random.sample(PROBLEMS, k=random.randint(0, 3)),
                recommendations=random.sample(RECOMMENDATIONS, k=random.randint(1, 3)),
                missing_documents=random.sample(["Discharge Summary", "FIR", "Original Invoice"], k=random.randint(0, 2)),
            )
            db.add(decision)
            db.commit()
            db.refresh(decision)

            analysis = compute_analysis_fields(claim, decision, payable)
            for key, value in analysis.items():
                setattr(decision, key, value)
            db.commit()

            if status == ClaimStatus.PENDING_REVIEW:
                db.add(
                    HumanReview(
                        claim_id=claim.id,
                        reason="AI confidence below threshold — expert consultation recommended",
                        assigned_to=claim.assigned_agent,
                        status=HumanReviewStatus.IN_PROGRESS,
                    )
                )
                db.commit()

        demo = db.query(Customer).filter(Customer.email == "priya.sharma@example.com").first()
        if not demo:
            demo = customers[0]
        print("Enterprise seed complete.")
        print(f"  Customers: {db.query(Customer).count()}")
        print(f"  Policies: {db.query(Policy).count()}")
        print(f"  Claims: {db.query(Claim).count()}")
        print(f"  Experts: {db.query(PolicyAgent).count()}")
        print(f"  Demo customer: {demo.email} / password123 / OTP 112233")
        print(f"  Demo expert: expert1@claimcopilot.in / password123 / OTP 112233")
        print(f"  Demo insurer: insurer1@claimcopilot.in / password123 / OTP 112233")
        demo_submitted = (
            db.query(Claim)
            .filter(Claim.status == ClaimStatus.SUBMITTED_TO_INSURER)
            .first()
        )
        if not demo_submitted and experts:
            fallback = db.query(Claim).order_by(Claim.updated_at.desc()).first()
            if fallback:
                fallback.status = ClaimStatus.SUBMITTED_TO_INSURER
                fallback.assigned_agent_id = experts[0].id
                fallback.assigned_agent = experts[0].full_name
                db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    seed_enterprise(reset=args.reset)
