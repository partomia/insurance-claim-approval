import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base
from models.chat import ChatRole


class AssistantPersona(str, enum.Enum):
    CUSTOMER_COPILOT = "customer_copilot"
    EXPERT_COPILOT = "expert_copilot"


class AssistantOwnerType(str, enum.Enum):
    CUSTOMER = "customer"
    AGENT = "agent"


class AssistantThreadType(str, enum.Enum):
    GENERAL = "general"
    CLAIM = "claim"


class AssistantSession(Base):
    __tablename__ = "assistant_sessions"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "persona", name="uq_assistant_session_owner_persona"),
    )

    id = Column(Integer, primary_key=True, index=True)
    owner_type = Column(Enum(AssistantOwnerType), nullable=False, index=True)
    owner_id = Column(Integer, nullable=False, index=True)
    persona = Column(Enum(AssistantPersona), nullable=False)
    long_term_memory_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    threads = relationship("AssistantThread", back_populates="session", cascade="all, delete-orphan")


class AssistantThread(Base):
    __tablename__ = "assistant_threads"
    __table_args__ = (
        UniqueConstraint("session_id", "thread_type", "claim_id", name="uq_assistant_thread_claim"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("assistant_sessions.id"), nullable=False, index=True)
    thread_type = Column(Enum(AssistantThreadType), nullable=False)
    claim_id = Column(
        Integer,
        ForeignKey("claims.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(255), nullable=False, default="General chat")
    summary_text = Column(Text, nullable=True)
    message_count = Column(Integer, nullable=False, default=0)
    last_compacted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = relationship("AssistantSession", back_populates="threads")
    messages = relationship("AssistantMessage", back_populates="thread", cascade="all, delete-orphan")
    claim = relationship("Claim")


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    # Composite index covers every hot query (load window / history / compaction):
    # they all filter by thread_id and order by created_at.
    __table_args__ = (
        Index("ix_assistant_messages_thread_created", "thread_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("assistant_threads.id"), nullable=False, index=True)
    role = Column(Enum(ChatRole), nullable=False)
    content = Column(Text, nullable=False)
    context_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    thread = relationship("AssistantThread", back_populates="messages")
