"""Backward-compatible query helper for LangGraph workflow."""

from services.rag_service import rag_service


def query_policy(query: str, n_results: int = 2, policy_id: int | None = None) -> str:
    clauses = rag_service.retrieve(query, top_k=n_results, policy_id=policy_id)
    if not clauses:
        return ""
    return " ".join(c.clause_text for c in clauses)
