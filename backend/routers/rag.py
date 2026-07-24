from fastapi import APIRouter

from rag.chroma_store import chroma_store
from config import get_settings

router = APIRouter(prefix="/api/rag", tags=["RAG"])
settings = get_settings()


@router.get("/status")
def rag_status():
    return {
        "collection": settings.chroma_collection_name,
        "chroma_db_path": settings.chroma_db_path,
        "chroma_count": chroma_store.count(),
    }
