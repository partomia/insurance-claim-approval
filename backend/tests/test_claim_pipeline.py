from unittest.mock import patch

from services.claim_pipeline import run_claim_pipeline_from


@patch("services.claim_pipeline.finalize_claim", return_value={"status": "PENDING_REVIEW"})
@patch("services.claim_pipeline._run_rag_retrieval", return_value={"retrieved_clauses": [{"section_ref": "Sec. 5.1"}]})
@patch("services.claim_pipeline._run_fraud_detection", return_value={"fraud_score": 0.2})
@patch("services.claim_pipeline._run_evidence_analysis", return_value={"evidence_mismatch": False})
@patch("services.claim_pipeline._load_cached_early_steps")
@patch("services.claim_pipeline.progress_service.publish")
@patch("services.claim_pipeline.SessionLocal")
def test_run_from_evidence_analysis_skips_early_steps(
    mock_session,
    mock_publish,
    mock_cached,
    mock_evidence,
    mock_fraud,
    mock_rag,
    mock_finalize,
):
    mock_cached.return_value = {
        "policy": {"eligible": True},
        "rag": {"retrieved_clauses": []},
        "customer": {"customer_risk_score": 0.1},
    }

    db = mock_session.return_value
    claim = type("Claim", (), {"status": None, "pipeline_run_id": 0})()
    db.query.return_value.options.return_value.filter.return_value.first.return_value = claim

    run_claim_pipeline_from(42, "evidence_analysis")

    mock_cached.assert_called_once_with(42)
    mock_evidence.assert_called_once_with(42)
    mock_rag.assert_called_once_with(42)
    mock_fraud.assert_called_once()
    mock_finalize.assert_called_once()

    reset_calls = [c for c in mock_publish.call_args_list if c[0][1] == "pipeline_reset"]
    assert len(reset_calls) == 1
    assert reset_calls[0][0][4]["from_step"] == "evidence_analysis"

    published_steps = [c[0][1] for c in mock_publish.call_args_list]
    assert "policy_validation" not in published_steps
    assert "customer_profile" not in published_steps
