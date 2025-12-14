from __future__ import annotations

import logging
from typing import List, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

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
        query_vec = OllamaEmbeddings().embed_query(query)
        distance = models.Chunk.embedding.cosine_distance(query_vec)
        stmt = select(models.Chunk).order_by(distance).limit(top_k)
        return db.scalars(stmt).all()

    # Fallback for tests (SQLite): return earliest chunks for determinism
    return db.scalars(select(models.Chunk).order_by(models.Chunk.id).limit(top_k)).all()
