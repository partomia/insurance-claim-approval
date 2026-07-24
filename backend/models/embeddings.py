from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


class PolicyClauseEmbedding(Base):
    __tablename__ = "policy_clause_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False)
    section_ref = Column(String, nullable=False)
    clause_text = Column(Text, nullable=False)
    faiss_id = Column(Integer, nullable=True)
    embedding_metadata = Column(JSON, default=dict, nullable=False)

    policy = relationship("Policy", back_populates="clause_embeddings")
