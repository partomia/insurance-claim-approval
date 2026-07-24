import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import chromadb
import numpy as np
from chromadb.api.models.Collection import Collection
from langchain_openai import OpenAIEmbeddings

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
EMBEDDING_DIMENSION = 1536

SECTION_REF_PATTERN = re.compile(
    r"(?:Section|Sec\.?|§)\s*(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)


def extract_section_ref(text: str) -> Optional[str]:
    """Pull the first policy section reference from chunk text, e.g. 'Sec. 5.5'."""
    match = SECTION_REF_PATTERN.search(text or "")
    if match:
        return f"Sec. {match.group(1)}"
    return None


def section_ref_for_chunk(
    chunk: str,
    *,
    fallback_prefix: str = "Policy Schedule",
    index: int,
    total: int,
) -> str:
    extracted = extract_section_ref(chunk)
    if extracted:
        return extracted if total == 1 else f"{extracted} (part {index + 1})"
    if total == 1:
        return fallback_prefix
    if fallback_prefix.startswith(("Sec.", "Section")):
        return f"{fallback_prefix} (part {index + 1})"
    return f"{fallback_prefix} {index + 1}"


@dataclass
class RetrievedClause:
    section_ref: str
    clause_text: str
    similarity_score: float
    policy_id: int
    metadata: dict


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


class ChromaStore:
    def __init__(self) -> None:
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection: Optional[Collection] = None
        self._embeddings: Optional[OpenAIEmbeddings] = None

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            path = Path(settings.chroma_db_path)
            path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(path))
        return self._client

    def ensure_collection(self) -> Collection:
        if self._collection is None:
            name = settings.chroma_collection_name
            try:
                self._collection = self.client.get_collection(name=name)
            except Exception:
                self._collection = self.client.create_collection(name=name)
        return self._collection

    def rebuild_collection(self) -> Collection:
        name = settings.chroma_collection_name
        try:
            self.client.delete_collection(name=name)
        except Exception:
            pass
        self._collection = self.client.create_collection(name=name)
        return self._collection

    @property
    def embeddings(self) -> Optional[OpenAIEmbeddings]:
        if self._embeddings is None and self._has_valid_api_key():
            self._embeddings = OpenAIEmbeddings(
                model=settings.embedding_model,
                openai_api_key=settings.openai_api_key,
            )
        return self._embeddings

    def _has_valid_api_key(self) -> bool:
        key = settings.openai_api_key or ""
        return bool(key) and not key.startswith("your_") and key != "sk-"

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._has_valid_api_key():
            rng = np.random.default_rng(42)
            vectors = rng.standard_normal((len(texts), EMBEDDING_DIMENSION)).astype("float32")
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors = vectors / norms
            return vectors.tolist()
        return self.embeddings.embed_documents(texts)

    def _embed_query(self, query: str) -> list[float]:
        if not self._has_valid_api_key():
            rng = np.random.default_rng(hash(query) % 2**32)
            vector = rng.standard_normal((EMBEDDING_DIMENSION,)).astype("float32")
            norm = np.linalg.norm(vector)
            if norm == 0:
                return vector.tolist()
            return (vector / norm).tolist()
        return self.embeddings.embed_query(query)

    def count(self) -> int:
        return self.ensure_collection().count()

    def add_clauses(
        self,
        clauses: list[dict[str, Any]],
        *,
        ids: Optional[list[str]] = None,
    ) -> list[str]:
        if not clauses:
            return []

        collection = self.ensure_collection()
        texts = [c["clause_text"] for c in clauses]
        embeddings = self._embed_texts(texts)

        chroma_ids = ids or [
            c.get("chroma_id") or f"policy-{c['policy_id']}-clause-{i}" for i, c in enumerate(clauses)
        ]
        metadatas = [
            {
                "policy_id": int(c["policy_id"]),
                "section_ref": str(c.get("section_ref", "Section")),
                "source": str(c.get("source", "clause")),
                "filename": str(c.get("filename", "")),
                "document_id": int(c["document_id"]) if c.get("document_id") is not None else -1,
            }
            for c in clauses
        ]

        collection.upsert(
            ids=chroma_ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        return chroma_ids

    def query_clauses(
        self,
        query: str,
        top_k: int = 5,
        policy_id: Optional[int] = None,
    ) -> list[RetrievedClause]:
        collection = self.ensure_collection()
        if collection.count() == 0:
            return []

        query_embedding = self._embed_query(query)
        where: Optional[dict[str, Any]] = None
        if policy_id is not None:
            where = {"policy_id": int(policy_id)}

        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, collection.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            kwargs["where"] = where

        results = collection.query(**kwargs)

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        clauses: list[RetrievedClause] = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            if not meta:
                continue
            similarity = round(max(0.0, 1.0 - float(dist)), 4)
            clauses.append(
                RetrievedClause(
                    section_ref=str(meta.get("section_ref", "Section")),
                    clause_text=doc or "",
                    similarity_score=similarity,
                    policy_id=int(meta.get("policy_id", 0)),
                    metadata={
                        "source": meta.get("source", ""),
                        "filename": meta.get("filename", ""),
                    },
                )
            )
        return clauses[:top_k]

    def count_by_policy_id(self, policy_id: int) -> int:
        collection = self.ensure_collection()
        if collection.count() == 0:
            return 0

        try:
            results = collection.get(where={"policy_id": int(policy_id)}, include=[])
            return len(results.get("ids") or [])
        except Exception as exc:
            logger.warning("Chroma count failed for policy %s: %s", policy_id, exc)
            return 0

    def delete_by_policy_id(self, policy_id: int) -> int:
        collection = self.ensure_collection()
        if collection.count() == 0:
            return 0

        try:
            results = collection.get(where={"policy_id": int(policy_id)}, include=[])
            ids = results.get("ids") or []
            if ids:
                collection.delete(ids=ids)
            return len(ids)
        except Exception as exc:
            logger.warning("Chroma delete failed for policy %s: %s", policy_id, exc)
            return 0

    def delete_by_document_id(self, policy_id: int, document_id: int) -> int:
        collection = self.ensure_collection()
        if collection.count() == 0:
            return 0

        try:
            results = collection.get(
                where={"$and": [{"policy_id": int(policy_id)}, {"document_id": int(document_id)}]},
                include=[],
            )
            ids = results.get("ids") or []
            if ids:
                collection.delete(ids=ids)
            return len(ids)
        except Exception as exc:
            logger.warning(
                "Chroma delete failed for policy %s document %s: %s",
                policy_id,
                document_id,
                exc,
            )
            return 0


chroma_store = ChromaStore()
