from __future__ import annotations

import logging
import time
from typing import List

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
DEFAULT_EMBED_DIM = 768

# Configurações de retry
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # segundos
MAX_BACKOFF = 10.0  # segundos


class OllamaClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.embed_model = self.settings.ollama_embed_model

    def _post_embeddings(self, texts: List[str], timeout: int = 60) -> dict:
        url = f"{self.base_url}/api/embed"
        payload = {"model": self.embed_model, "input": texts}  # lista OK
        logger.info("Embedding request: %d texts to model %s", len(texts), self.embed_model)
        resp = httpx.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
        

    def _post_with_retry(self, texts: List[str]) -> dict:
        """Executa POST com retry e backoff exponencial."""
        last_error = None
        backoff = INITIAL_BACKOFF

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self._post_embeddings(texts)
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "Timeout na tentativa %d/%d para %d textos, aguardando %.1fs",
                    attempt, MAX_RETRIES, len(texts), backoff
                )
            except httpx.HTTPStatusError as e:
                last_error = e
                # Não retry em erros 4xx (client error)
                if 400 <= e.response.status_code < 500:
                    logger.error("Erro de cliente (HTTP %d): %s", e.response.status_code, e.response.text)
                    raise
                logger.warning(
                    "Erro HTTP %d na tentativa %d/%d, aguardando %.1fs",
                    e.response.status_code, attempt, MAX_RETRIES, backoff
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "Erro na tentativa %d/%d: %s, aguardando %.1fs",
                    attempt, MAX_RETRIES, str(e), backoff
                )

            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)

        logger.error("Falha após %d tentativas de embedding", MAX_RETRIES)
        raise RuntimeError(f"Failed to embed text after {MAX_RETRIES} attempts") from last_error

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Gera embeddings para uma lista de textos.

        Args:
            texts: Lista de textos para embedding

        Returns:
            Lista de vetores de embedding (dimensão 768)

        Raises:
            RuntimeError: Se falhar após todas as tentativas
        """
        if not texts:
            logger.warning("Lista de textos vazia para embedding")
            return []

        if self.settings.app_env.lower() == "test":
            # Deterministic vector for testing; length matches pgvector dim.
            return [[0.1] * DEFAULT_EMBED_DIM for _ in texts]

        # Log tamanho dos textos para debug
        total_chars = sum(len(t) for t in texts)
        logger.info("Embedding %d textos (total: %d chars, média: %.0f chars/texto)",
                    len(texts), total_chars, total_chars / len(texts) if texts else 0)

        try:
            data = self._post_with_retry(texts)
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
        """Faz embedding texto por texto (fallback para batches que falham)."""
        results: List[List[float]] = []
        for idx, text in enumerate(texts):
            try:
                data = self._post_with_retry([text])
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
                    results.append(self._normalize_vector(vecs[0], idx + 1, len(texts)))
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

