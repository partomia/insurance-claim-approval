from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class CustomerProfileSignal(Base):
    """Bureau / driving-record / relationship attributes for a customer — the
    inputs to the Customer Trust Score (services/customer_trust_service.py).

    Sources:
      - GOLD_PIPELINE: scripts/ingest_lakehouse.py, from the CDE gold table
        insurance_lakehouse.customer_profile_signals (matched by email).
      - DEMO_SEED: scripts/seed.py, for the non-lakehouse demo customers so
        OLTP-only deployments can exercise the same scoring.

    One row per Customer (1:1). A customer with no row is "UNSCORED" and gets
    exactly the pre-trust-score decision behaviour.
    """

    __tablename__ = "customer_profile_signals"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), unique=True, nullable=False, index=True)

    credit_score = Column(Integer, nullable=True)  # 300-900; NULL = no bureau hit
    credit_score_percentile = Column(Float, nullable=True)
    credit_band = Column(String, nullable=True)  # EXCELLENT / GOOD / FAIR / POOR / NO_HIT
    loan_defaults_12m = Column(Integer, default=0, nullable=False)
    active_vehicle_loan = Column(Boolean, default=False, nullable=False)

    driver_age = Column(Integer, nullable=True)  # stored for reference; not used in scoring
    years_licensed = Column(Integer, nullable=True)
    traffic_violations_3y = Column(Integer, default=0, nullable=False)
    dui_history = Column(Boolean, default=False, nullable=False)
    driving_record_band = Column(String, nullable=True)  # CLEAN / MINOR / POOR

    address_changed_90d = Column(Boolean, default=False, nullable=False)
    years_with_insurer = Column(Float, default=0.0, nullable=False)
    policies_held = Column(Integer, default=1, nullable=False)
    other_insurer_claims_3y = Column(Integer, default=0, nullable=False)

    source = Column(String, default="GOLD_PIPELINE", nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="profile_signal")
