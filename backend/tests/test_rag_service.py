from services.rag_service import RAGService, RetrievedClause


def test_clause_clarity_score():
    service = RAGService()
    clauses = [
        RetrievedClause("4.2", "text", 0.9, 1, {}),
        RetrievedClause("7.1", "text", 0.8, 1, {}),
    ]
    score = service.clause_clarity_score(clauses)
    assert 0.8 <= score <= 0.9


def test_to_dict_list():
    service = RAGService()
    clauses = [RetrievedClause("4.2", "coverage text", 0.85, 1, {})]
    result = service.to_dict_list(clauses)
    assert result[0]["section_ref"] == "4.2"
    assert result[0]["similarity_score"] == 0.85
