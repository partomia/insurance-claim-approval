import secrets
from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class InsurerAuthSession(Base):
    __tablename__ = "insurer_auth_sessions"

    id = Column(Integer, primary_key=True, index=True)
    insurer_id = Column(Integer, ForeignKey("insurer_users.id"), nullable=False, index=True)
    refresh_token = Column(String(128), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    insurer = relationship("InsurerUser", back_populates="auth_sessions")

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def default_expiry(days: int = 30) -> datetime:
        return datetime.utcnow() + timedelta(days=days)
