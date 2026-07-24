from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class PolicyAgent(Base):
    __tablename__ = "policy_agents"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    department = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    auth_sessions = relationship(
        "AgentAuthSession",
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    assigned_claims = relationship("Claim", back_populates="assigned_policy_agent")
