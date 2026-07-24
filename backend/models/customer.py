from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    gov_id_hash = Column(String, nullable=True)
    blacklist_flag = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    policies = relationship("Policy", back_populates="customer")
    claims = relationship("Claim", back_populates="customer")
    auth_sessions = relationship("AuthSession", back_populates="customer", cascade="all, delete-orphan")
    profile = relationship("CustomerProfile", back_populates="customer", uselist=False, cascade="all, delete-orphan")
    assistant_messages = relationship(
        "CustomerChatMessage", back_populates="customer", cascade="all, delete-orphan"
    )
