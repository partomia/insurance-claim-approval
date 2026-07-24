import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


class ChatRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ClaimChatMessage(Base):
    __tablename__ = "claim_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    role = Column(Enum(ChatRole), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="chat_messages")


class AgentChatMessage(Base):
    __tablename__ = "agent_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("policy_agents.id"), nullable=False, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    role = Column(Enum(ChatRole), nullable=False)
    content = Column(Text, nullable=False)
    context_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    agent = relationship("PolicyAgent")
    claim = relationship("Claim")
    customer = relationship("Customer")


class CustomerChatMessage(Base):
    __tablename__ = "customer_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    role = Column(Enum(ChatRole), nullable=False)
    content = Column(Text, nullable=False)
    context_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="assistant_messages")
