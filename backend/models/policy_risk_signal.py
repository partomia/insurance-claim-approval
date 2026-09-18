from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class PolicyRiskSignal(Base):
    """Fraud/risk analytics for a policy, sourced from the CDE claims-analytics
    medallion pipeline's Iceberg gold table (insurance_lakehouse.policy_risk_signals)
    — see cde/README.md § "Claims-analytics design (Phase 2b)".

    Populated exclusively by scripts/ingest_lakehouse.py (Phase 3); the live
    app never writes to this table directly. One row per Policy (1:1),
    matched by policy_number at ingest time — only policies present in both
    policy_master (the ~60 "active" gold rows) and policy_risk_signals (the
    ~800-policy claims-history population) get a row here, so not every
    Policy will have one.
    """

    __tablename__ = "policy_risk_signals"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), unique=True, nullable=False, index=True)

    total_claims_count = Column(Integer, default=0, nullable=False)
    claims_count_12m = Column(Integer, default=0, nullable=False)
    total_claimed_amount = Column(Float, default=0.0, nullable=False)
    avg_claim_amount = Column(Float, default=0.0, nullable=False)
    amount_vs_segment_avg_pct = Column(Float, nullable=True)
    claim_frequency_percentile = Column(Float, nullable=True)
    linked_high_risk_garage = Column(Boolean, default=False, nullable=False)
    fraud_risk_score = Column(Float, nullable=False)
    claim_risk_band = Column(String, nullable=False)  # LOW / MEDIUM / HIGH

    source = Column(String, default="GOLD_PIPELINE", nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    policy = relationship("Policy", back_populates="risk_signal")
