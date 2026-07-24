from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer

from database import Base


class ClaimProgressEvent(Base):
    __tablename__ = "claim_progress_events"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
