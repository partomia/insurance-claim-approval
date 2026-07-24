import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from models.embeddings import PolicyClauseEmbedding
from models.policy import PolicyDocument
from rag.chroma_store import extract_section_ref
from services.rag_service import rag_service


def reindex_chroma(rebuild: bool = True) -> int:
    db = SessionLocal()
    total = 0
    try:
        if rebuild:
            rag_service._store.rebuild_collection()

        clause_rows = db.query(PolicyClauseEmbedding).all()
        if clause_rows:
            clauses = [
                {
                    "policy_id": row.policy_id,
                    "section_ref": row.section_ref,
                    "clause_text": row.clause_text,
                    "embedding_metadata": row.embedding_metadata or {},
                    "source": (row.embedding_metadata or {}).get("source", "seed"),
                    "chroma_id": f"clause-{row.id}",
                }
                for row in clause_rows
            ]
            rag_service._store.add_clauses(clauses)
            total += len(clauses)
            print(f"Indexed {len(clauses)} clause embeddings into Chroma.")

        doc_rows = db.query(PolicyDocument).all()
        doc_chunks = 0
        for doc in doc_rows:
            if not doc.content_text:
                continue
            section_ref = doc.section_ref
            if section_ref in ("Upload", "ClaimUpload", None, ""):
                section_ref = extract_section_ref(doc.content_text) or "Policy Schedule"
                doc.section_ref = section_ref
            doc_chunks += rag_service.index_policy_document(
                db,
                doc.policy_id,
                doc.content_text,
                section_ref=section_ref,
                source=getattr(doc.source, "value", str(doc.source)),
                filename=doc.title,
                document_id=doc.id,
            )
        total += doc_chunks
        db.commit()
        print(f"Indexed {doc_chunks} document chunks from {len(doc_rows)} policy documents.")

        count = rag_service.count()
        print(f"Chroma collection total: {count} vectors.")
        return total
    finally:
        db.close()


if __name__ == "__main__":
    reindex_chroma(rebuild=True)
