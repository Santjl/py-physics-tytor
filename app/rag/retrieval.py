from __future__ import annotations

import logging
from typing import List, Sequence

from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy import func, cast
from pgvector.sqlalchemy import Vector
from sqlalchemy import func

from app import models
from app.core.config import get_settings
from app.rag.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class OllamaEmbeddings:
    """LangChain-compatible embedding wrapper using Ollama HTTP API."""

    def __init__(self) -> None:
        self.client = OllamaClient()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.client.embed(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.client.embed([text])[0]


def retrieve_chunks(db: Session, query: str, top_k: int = 8) -> Sequence[models.Chunk]:
    settings = get_settings()
    if db.bind and db.bind.dialect.name == "postgresql":
        # Skip embedding call if there are no chunks stored
        has_chunks = db.scalar(select(models.Chunk.id).limit(1))
        if not has_chunks:
            return []

        try:
            query_vec = OllamaEmbeddings().embed_query(query)
            # Validate embedding shape
            if not isinstance(query_vec, list) or not all(isinstance(x, (int, float)) for x in query_vec):
                raise RuntimeError("Embedding response is not a list of numbers")
        except Exception:
            logger.exception("Falling back: failed to embed query for retrieval")
            return db.scalars(select(models.Chunk).order_by(models.Chunk.id).limit(top_k)).all()

        # Normalize query vector size and type to avoid pgvector errors
        dim = models.EmbeddingType.dimensions
        if len(query_vec) != dim:
            query_vec = (query_vec + [0.0] * dim)[:dim]
        distance_expr = func.cosine_distance(models.Chunk.embedding, cast(query_vec, Vector(dim)))
        stmt = select(models.Chunk).order_by(distance_expr).limit(top_k)
        return db.scalars(stmt).all()

    # Fallback for tests (SQLite): return earliest chunks for determinism
    return db.scalars(select(models.Chunk).order_by(models.Chunk.id).limit(top_k)).all()
