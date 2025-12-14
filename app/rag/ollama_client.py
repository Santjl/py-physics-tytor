from __future__ import annotations

import logging
from typing import List

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.embed_model = self.settings.ollama_embed_model

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self.settings.app_env.lower() == "test":
            # Deterministic vector for testing; length matches pgvector dim.
            return [[0.1] * 768 for _ in texts]

        url = f"{self.base_url}/api/embeddings"
        payload = {"model": self.embed_model, "input": texts}
        try:
            resp = httpx.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Embedding request failed")
            raise RuntimeError("Failed to embed text") from exc

        # Ollama returns either a single embedding or list depending on input
        embeddings = data.get("embeddings") or [data.get("embedding")]
        if not embeddings or len(embeddings) != len(texts):
            raise RuntimeError("Unexpected embedding response size")
        return embeddings
