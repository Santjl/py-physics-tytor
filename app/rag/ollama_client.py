from __future__ import annotations

import logging
from typing import List

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
DEFAULT_EMBED_DIM = 768


class OllamaClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.embed_model = self.settings.ollama_embed_model

    def _post_embeddings(self, texts: List[str]) -> dict:
        url = f"{self.base_url}/api/embeddings"
        payload = {"model": self.embed_model, "input": texts}
        logger.info("Embedding request: %d texts to model %s", len(texts), self.embed_model)
        resp = httpx.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self.settings.app_env.lower() == "test":
            # Deterministic vector for testing; length matches pgvector dim.
            return [[0.1] * 768 for _ in texts]

        try:
            data = self._post_embeddings(texts)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Embedding request failed")
            raise RuntimeError("Failed to embed text") from exc

        embeddings = data.get("embeddings")
        if embeddings is None:
            single = data.get("embedding")
            if single is not None:
                embeddings = [single]

        if not embeddings:
            logger.warning("Empty embedding payload, retrying one-by-one (%d texts)", len(texts))
            embeddings = self._embed_one_by_one(texts)

        if len(embeddings) != len(texts):
            if len(embeddings) == 1 and len(texts) > 1:
                logger.warning("Embedding response had 1 vector for %d inputs; retrying one-by-one", len(texts))
                embeddings = self._embed_one_by_one(texts)
            else:
                raise RuntimeError(
                    f"Unexpected embedding response size: got {len(embeddings)}, expected {len(texts)}"
                )

        embeddings = [self._normalize_vector(vec, idx, len(texts)) for idx, vec in enumerate(embeddings, start=1)]
        return embeddings

    def _embed_one_by_one(self, texts: List[str]) -> List[List[float]]:
        results: List[List[float]] = []
        for idx, text in enumerate(texts):
            try:
                data = self._post_embeddings([text])
                vecs = data.get("embeddings")
                if vecs is None:
                    single = data.get("embedding")
                    vecs = [single] if single is not None else None
                if not vecs:
                    logger.warning(
                        "Empty embedding payload for text %d/%d; using zero vector", idx + 1, len(texts)
                    )
                    results.append([0.0] * DEFAULT_EMBED_DIM)
                else:
                    results.append(self._normalize_vector(vecs[0], idx, len(texts)))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed embedding for text %d/%d", idx + 1, len(texts))
                raise RuntimeError("Failed to embed text") from exc
        return results

    def _normalize_vector(self, vec, idx: int, total: int) -> List[float]:
        if not vec:
            logger.warning("Empty embedding vector for text %d/%d; using zero vector", idx, total)
            return [0.0] * DEFAULT_EMBED_DIM

        # guarantee list[float]
        try:
            vec = list(vec)
        except TypeError:
            logger.warning("Non-iterable embedding vector for text %d/%d; using zero vector", idx, total)
            return [0.0] * DEFAULT_EMBED_DIM

        # validate dimension; pad/truncate to be tolerant
        if len(vec) != DEFAULT_EMBED_DIM:
            logger.warning(
                "Unexpected embedding dim for text %d/%d: got %d, expected %d",
                idx,
                total,
                len(vec),
                DEFAULT_EMBED_DIM,
            )
            if len(vec) > DEFAULT_EMBED_DIM:
                vec = vec[:DEFAULT_EMBED_DIM]
            else:
                vec = vec + [0.0] * (DEFAULT_EMBED_DIM - len(vec))

        return vec

