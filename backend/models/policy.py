import enum
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


class PolicyDocumentSource(str, enum.Enum):
    SEED = "SEED"
    UPLOAD = "UPLOAD"


class PolicyStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class PremiumPaymentStatus(str, enum.Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    OVERDUE = "OVERDUE"


class Policy(Base):
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)
    policy_number = Column(String, unique=True, index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("insurance_providers.id"), nullable=True, index=True)
    policy_type = Column(String, nullable=False)
    premium_amount = Column(Float, default=0.0, nullable=False)
    status = Column(Enum(PolicyStatus), default=PolicyStatus.ACTIVE, nullable=False)
    coverage_limit = Column(Float, nullable=False)
    deductible = Column(Float, default=0.0, nullable=False)
    co_pay_pct = Column(Float, default=0.0, nullable=False)
    exclusions = Column(JSON, default=list, nullable=False)
    waiting_period_days = Column(Integer, default=0, nullable=False)
    effective_date = Column(DateTime, nullable=False)
    expiry_date = Column(DateTime, nullable=False)
    depreciation_rate = Column(Float, default=0.0, nullable=False)

    customer = relationship("Customer", back_populates="policies")
    provider = relationship("InsuranceProvider", back_populates="policies")
    claims = relationship("Claim", back_populates="policy")
    premium_payments = relationship("PremiumPayment", back_populates="policy")
    clause_embeddings = relationship("PolicyClauseEmbedding", back_populates="policy")
    policy_documents = relationship("PolicyDocument", back_populates="policy")


class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False)
    title = Column(String, nullable=False)
    section_ref = Column(String, nullable=False)
    content_text = Column(Text, nullable=False)
    file_path = Column(String, nullable=True)
    source = Column(Enum(PolicyDocumentSource), default=PolicyDocumentSource.SEED, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    policy = relationship("Policy", back_populates="policy_documents")


class PremiumPayment(Base):
    __tablename__ = "premium_payments"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False)
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    status = Column(Enum(PremiumPaymentStatus), default=PremiumPaymentStatus.PAID, nullable=False)

    policy = relationship("Policy", back_populates="premium_payments")
