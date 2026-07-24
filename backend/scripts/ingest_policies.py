"""Build Chroma index from policy clause embeddings and documents in the database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.reindex_chroma import reindex_chroma


def ingest_from_db(rebuild: bool = True) -> int:
    return reindex_chroma(rebuild=rebuild)


if __name__ == "__main__":
    ingest_from_db(rebuild=True)
