"""Ensure demo insurer account exists for local development."""

from sqlalchemy.orm import Session

from dependencies import get_password_hash
from models.insurer_user import InsurerUser

DEMO_INSURER = {
    "email": "insurer1@claimcopilot.in",
    "full_name": "Rajesh Iyer",
    "password": "password123",
    "department": "Senior Claims Adjuster",
}


def ensure_demo_insurer(db: Session) -> InsurerUser | None:
    """Create the demo insurer user if missing (idempotent)."""
    existing = db.query(InsurerUser).filter(InsurerUser.email == DEMO_INSURER["email"]).first()
    if existing:
        return existing

    insurer = InsurerUser(
        email=DEMO_INSURER["email"],
        full_name=DEMO_INSURER["full_name"],
        hashed_password=get_password_hash(DEMO_INSURER["password"]),
        department=DEMO_INSURER["department"],
    )
    db.add(insurer)
    db.commit()
    db.refresh(insurer)
    return insurer
