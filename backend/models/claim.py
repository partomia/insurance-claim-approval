import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


class ClaimStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATE = "ESCALATE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    PENDING_REVIEW = "PENDING_REVIEW"
    REQUEST_MORE_INFO = "REQUEST_MORE_INFO"
    SUBMISSION_READY = "SUBMISSION_READY"
    SUBMITTED_TO_INSURER = "SUBMITTED_TO_INSURER"


class DocumentType(str, enum.Enum):
    PROOF = "PROOF"
    POLICE_REPORT = "POLICE_REPORT"
    MEDICAL = "MEDICAL"
    GOV_ID = "GOV_ID"
    INVOICE = "INVOICE"
    POLICY_PAPER = "POLICY_PAPER"
    OTHER = "OTHER"


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, index=True)
    claim_number = Column(String, unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=True)
    incident_description = Column(Text, nullable=False)
    incident_datetime = Column(DateTime, nullable=False)
    location = Column(String, nullable=False)
    claim_amount = Column(Float, nullable=False)
    status = Column(Enum(ClaimStatus), default=ClaimStatus.DRAFT, nullable=False)
    submission_step = Column(Integer, default=1, nullable=False)
    policy_context_json = Column(JSON, default=dict, nullable=False)
    policy_docs_source = Column(String, nullable=True)
    escalation_flags = Column(JSON, default=list, nullable=False)
    escalation_messages = Column(JSON, default=list, nullable=False)
    assigned_agent = Column(String, nullable=True)
    assigned_agent_id = Column(Integer, ForeignKey("policy_agents.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True)
    evidence_mismatch = Column(Boolean, default=False, nullable=False)
    evidence_issues = Column(JSON, default=list, nullable=False)
    pipeline_run_id = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="claims")
    policy = relationship("Policy", back_populates="claims")
    assigned_policy_agent = relationship("PolicyAgent", back_populates="assigned_claims")
    documents = relationship("ClaimDocument", back_populates="claim", cascade="all, delete-orphan")
    fraud_assessment = relationship("FraudAssessment", back_populates="claim", uselist=False)
    decision = relationship("ClaimDecision", back_populates="claim", uselist=False)
    human_reviews = relationship("HumanReview", back_populates="claim")
    audit_logs = relationship("AuditLog", back_populates="claim")
    chat_messages = relationship("ClaimChatMessage", back_populates="claim", cascade="all, delete-orphan")


class ClaimDocument(Base):
    __tablename__ = "claim_documents"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    doc_type = Column(Enum(DocumentType), nullable=False)
    file_path = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    checksum = Column(String, nullable=False)
    ocr_text = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="documents")
