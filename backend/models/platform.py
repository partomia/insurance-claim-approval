import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


class KYCStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class InsuranceProvider(Base):
    __tablename__ = "insurance_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    logo_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    policies = relationship("Policy", back_populates="provider")


class CustomerProfile(Base):
    """Extended customer profile — one row per customer."""

    __tablename__ = "customer_profiles"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), unique=True, nullable=False)
    phone = Column(String, nullable=True)
    date_of_birth = Column(DateTime, nullable=True)
    kyc_status = Column(Enum(KYCStatus), default=KYCStatus.PENDING, nullable=False)
    kyc_gov_id_path = Column(String, nullable=True)
    kyc_face_verified = Column(Boolean, default=False, nullable=False)
    kyc_mobile_verified = Column(Boolean, default=False, nullable=False)
    kyc_verified_at = Column(DateTime, nullable=True)
    emergency_contacts = Column(JSON, default=list, nullable=False)
    saved_vehicles = Column(JSON, default=list, nullable=False)
    saved_garages = Column(JSON, default=list, nullable=False)
    preferred_providers = Column(JSON, default=list, nullable=False)
    dependents = Column(JSON, default=list, nullable=False)
    risk_profile = Column(JSON, default=dict, nullable=False)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="profile")
