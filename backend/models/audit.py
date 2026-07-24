import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base
from models.claim import ClaimStatus


class HumanReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class FraudAssessment(Base):
    __tablename__ = "fraud_assessments"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), unique=True, nullable=False)
    fraud_score = Column(Float, nullable=False)
    signals = Column(JSON, default=list, nullable=False)
    blacklist_hit = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="fraud_assessment")


class ClaimDecision(Base):
    __tablename__ = "claim_decisions"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), unique=True, nullable=False)
    status = Column(Enum(ClaimStatus), nullable=False)
    payable_amount = Column(Float, default=0.0, nullable=False)
    confidence_score = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    retrieved_clauses = Column(JSON, default=list, nullable=False)
    evidence_results = Column(JSON, default=list, nullable=False)
    fraud_score = Column(Float, nullable=False)
    human_review_required = Column(Boolean, default=False, nullable=False)
    payout_breakdown = Column(JSON, default=dict, nullable=False)
    approval_probability = Column(Float, nullable=True)
    coverage_estimate = Column(Float, nullable=True)
    expected_settlement = Column(Float, nullable=True)
    potential_problems = Column(JSON, default=list, nullable=False)
    recommendations = Column(JSON, default=list, nullable=False)
    missing_documents = Column(JSON, default=list, nullable=False)
    policy_clause_matches = Column(JSON, default=list, nullable=False)
    fraud_signals = Column(JSON, default=list, nullable=False)
    next_best_action = Column(String, nullable=True)
    ai_explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="decision")


class HumanReview(Base):
    __tablename__ = "human_reviews"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    reason = Column(Text, nullable=False)
    assigned_to = Column(String, nullable=True)
    status = Column(Enum(HumanReviewStatus), default=HumanReviewStatus.PENDING, nullable=False)
    reviewer_notes = Column(Text, nullable=True)
    decision_override = Column(Enum(ClaimStatus), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="human_reviews")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, default=dict, nullable=False)
    actor = Column(String, default="system", nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="audit_logs")
