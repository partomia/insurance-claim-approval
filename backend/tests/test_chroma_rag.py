import pytest

from config import get_settings
from rag.chroma_store import ChromaStore, chunk_text, extract_section_ref, section_ref_for_chunk
from services.rag_service import RAGService


@pytest.fixture
def isolated_rag(tmp_path, monkeypatch):
    chroma_path = str(tmp_path / "chroma_db")
    monkeypatch.setenv("CHROMA_DB_PATH", chroma_path)
    get_settings.cache_clear()

    store = ChromaStore()
    store._client = None
    store._collection = None
    store.rebuild_collection()
    return RAGService(store=store)


def test_chunk_text_overlap():
    text = "a" * 1000
    chunks = chunk_text(text, chunk_size=800, overlap=100)
    assert len(chunks) >= 2
    assert all(len(c) <= 800 for c in chunks)


def test_chroma_ingest_and_retrieve_by_policy(isolated_rag):
    rag = isolated_rag
    rag._store.add_clauses(
        [
            {
                "policy_id": 1,
                "section_ref": "Section 4.2",
                "clause_text": "Comprehensive coverage includes collision and theft.",
                "source": "test",
            },
            {
                "policy_id": 2,
                "section_ref": "Section 1.0",
                "clause_text": "Unrelated home policy flood exclusion.",
                "source": "test",
            },
        ]
    )

    results = rag.retrieve("collision coverage auto", top_k=3, policy_id=1)
    assert len(results) >= 1
    assert all(r.policy_id == 1 for r in results)
    assert "collision" in results[0].clause_text.lower()


def test_chroma_delete_by_policy(isolated_rag):
    rag = isolated_rag
    rag._store.add_clauses(
        [
            {
                "policy_id": 99,
                "section_ref": "Sec 1",
                "clause_text": "Policy ninety nine coverage text.",
                "source": "test",
            }
        ]
    )
    assert rag.count() == 1
    deleted = rag.delete_policy_vectors(99)
    assert deleted == 1
    assert rag.count() == 0


def test_rag_status_endpoint(client):
    response = client.get("/api/rag/status")
    assert response.status_code == 200
    data = response.json()
    assert data["collection"] == "insurance_policies"
    assert "chroma_count" in data


def test_extract_section_ref_from_text():
    text = "Section 5.5 — Water Damage Coverage\nRepairs must be documented with inspection reports."
    assert extract_section_ref(text) == "Sec. 5.5"


def test_section_ref_for_chunk_uses_extracted_ref():
    chunk = "Sec. 4.2 Collision coverage applies when..."
    assert section_ref_for_chunk(chunk, fallback_prefix="Policy Schedule", index=0, total=1) == "Sec. 4.2"


def test_section_ref_for_chunk_fallback_without_section():
    chunk = "General provisions for homeowners coverage and deductibles."
    assert section_ref_for_chunk(chunk, fallback_prefix="Policy Schedule", index=1, total=3) == "Policy Schedule 2"
    assert (
        section_ref_for_chunk(chunk, fallback_prefix="Sec. 5.1", index=2, total=3)
        == "Sec. 5.1 (part 3)"
    )


def test_index_policy_document_uses_section_refs(isolated_rag):
    rag = isolated_rag
    text = (
        "Section 5.5 Water Damage. Covered perils include sudden pipe bursts. " * 30
        + "Section 6.1 Exclusions. Flood damage from external sources is excluded. " * 30
    )
    count = rag.index_policy_document(
        db=None,  # type: ignore[arg-type]
        policy_id=5,
        text=text,
        section_ref="Policy Schedule",
        source="upload",
        filename="home_policy.pdf",
        document_id=10,
    )
    assert count >= 2
    results = rag.retrieve("water damage pipe burst", top_k=3, policy_id=5)
    assert len(results) >= 1
    refs = [r.section_ref for r in results]
    assert not any(ref.startswith("Upload-") for ref in refs)
    assert any("Sec." in ref or "Policy Schedule" in ref for ref in refs)


def test_index_policy_document_replaces_existing_chunks(isolated_rag):
    rag = isolated_rag
    text = "Section 3.1 Travel coverage. " * 40
    first = rag.index_policy_document(
        db=None,  # type: ignore[arg-type]
        policy_id=7,
        text=text,
        section_ref="Policy Schedule",
        filename="travel.pdf",
        document_id=99,
    )
    second = rag.index_policy_document(
        db=None,  # type: ignore[arg-type]
        policy_id=7,
        text=text + " Updated endorsement text. " * 10,
        section_ref="Policy Schedule",
        filename="travel.pdf",
        document_id=99,
    )
    assert first >= 1
    assert second >= 1
    assert rag.count() == second
    results = rag.retrieve("travel coverage", top_k=5, policy_id=7)
    assert len(results) >= 1
    assert all(r.policy_id == 7 for r in results)


def test_index_policy_document_chunks(isolated_rag):
    rag = isolated_rag
    text = "word " * 500
    count = rag.index_policy_document(
        db=None,  # type: ignore[arg-type]
        policy_id=5,
        text=text,
        section_ref="Policy Schedule",
        source="upload",
        filename="schedule.pdf",
        document_id=10,
    )
    assert count >= 2
    assert rag.count() >= 2
