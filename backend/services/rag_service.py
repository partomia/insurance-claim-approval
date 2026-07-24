import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.embeddings import PolicyClauseEmbedding
from rag.chroma_store import ChromaStore, RetrievedClause, chunk_text, chroma_store, section_ref_for_chunk

logger = logging.getLogger(__name__)

__all__ = ["RAGService", "RetrievedClause", "rag_service"]


class RAGService:
    def __init__(self, store: Optional[ChromaStore] = None) -> None:
        self._store = store or chroma_store

    def ingest_clauses(
        self,
        db: Session,
        clauses: list[dict[str, Any]],
        rebuild: bool = False,
    ) -> int:
        if rebuild:
            self._store.rebuild_collection()

        if not clauses:
            return 0

        chroma_ids = self._store.add_clauses(clauses)

        for clause, chroma_id in zip(clauses, chroma_ids):
            db_clause = PolicyClauseEmbedding(
                policy_id=clause["policy_id"],
                section_ref=clause["section_ref"],
                clause_text=clause["clause_text"],
                faiss_id=None,
                embedding_metadata={
                    **(clause.get("embedding_metadata") or {}),
                    "chroma_id": chroma_id,
                    "source": clause.get("source", "clause"),
                },
            )
            db.add(db_clause)

        db.commit()
        return len(clauses)

    def index_policy_document(
        self,
        db: Session | None,
        policy_id: int,
        text: str,
        *,
        section_ref: str = "Policy Schedule",
        source: str = "upload",
        filename: str = "",
        document_id: Optional[int] = None,
    ) -> int:
        chunks = chunk_text(text)
        if not chunks:
            return 0

        if document_id is not None:
            removed = self._store.delete_by_document_id(policy_id, document_id)
            if removed:
                logger.info(
                    "Replaced %s existing RAG chunks for policy_id=%s document_id=%s",
                    removed,
                    policy_id,
                    document_id,
                )

        fallback = section_ref if section_ref not in ("Upload", "ClaimUpload") else "Policy Schedule"
        clauses = [
            {
                "policy_id": policy_id,
                "document_id": document_id,
                "section_ref": section_ref_for_chunk(
                    chunk,
                    fallback_prefix=fallback,
                    index=i,
                    total=len(chunks),
                ),
                "clause_text": chunk,
                "source": source,
                "filename": filename,
                "chroma_id": f"policy-{policy_id}-doc-{document_id or 'x'}-chunk-{i}",
            }
            for i, chunk in enumerate(chunks)
        ]
        self._store.add_clauses(clauses)
        logger.info(
            "Indexed %s chunks for policy_id=%s from %s",
            len(clauses),
            policy_id,
            filename or section_ref,
        )
        return len(clauses)

    def delete_policy_vectors(self, policy_id: int) -> int:
        return self._store.delete_by_policy_id(policy_id)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        policy_id: Optional[int] = None,
    ) -> list[RetrievedClause]:
        return self._store.query_clauses(query, top_k=top_k, policy_id=policy_id)

    def clause_clarity_score(self, clauses: list[RetrievedClause]) -> float:
        if not clauses:
            return 0.5
        avg_sim = sum(c.similarity_score for c in clauses) / len(clauses)
        return min(max(avg_sim, 0.0), 1.0)

    def to_dict_list(self, clauses: list[RetrievedClause]) -> list[dict]:
        return [
            {
                "section_ref": c.section_ref,
                "clause_text": c.clause_text,
                "similarity_score": c.similarity_score,
                "policy_id": c.policy_id,
            }
            for c in clauses
        ]

    def count(self) -> int:
        return self._store.count()

    def count_for_policy(self, policy_id: int) -> int:
        return self._store.count_by_policy_id(policy_id)


rag_service = RAGService()
