from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import List, Tuple

import fitz
from sqlalchemy.orm import Session

from app import models
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.rag.chunking import build_chunks, estimate_tokens, MAX_INPUT_TOKENS
from app.rag.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# Configurações de processamento
MIN_CHUNK_LENGTH = 10  # Ignora chunks muito pequenos
MAX_EMPTY_PAGES_RATIO = 0.9  # Alerta se muitas páginas vazias

EXERCISE_MARKERS = [
    "exercicio",
    "exercicios",
    "problema",
    "questoes",
    "lista de exercicios",
    "resolva",
    "ex.:",
    "exemplo",
    "gabarito",
    "solucao",
]

CHAPTER_REGEX = re.compile(r"(?mi)^\s*cap[ií]tulo\s+\d+[^\n]*")
SECTION_REGEX = re.compile(r"(?mi)^\s*se[cç][aã]o\s+[\d\.]+[^\n]*")


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _classify_chunk_type(text: str) -> str:
    normalized = _strip_accents(text).lower()
    for marker in EXERCISE_MARKERS:
        if marker in normalized:
            return "exercise"
    return "theory" if normalized.strip() else "unknown"


def _extract_chapter_title(text: str) -> str | None:
    match = CHAPTER_REGEX.search(text)
    return match.group(0).strip() if match else None


def _extract_section_title(text: str) -> str | None:
    match = SECTION_REGEX.search(text)
    return match.group(0).strip() if match else None


def extract_pages(pdf_bytes: bytes) -> List[Tuple[int, str]]:
    """
    Extrai texto de cada página do PDF.

    Args:
        pdf_bytes: Conteúdo do PDF em bytes

    Returns:
        Lista de tuplas (número_página, texto)

    Raises:
        ValueError: Se o PDF estiver corrompido ou vazio
    """
    start = time.perf_counter()
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error("Falha ao abrir PDF: %s", str(e))
        raise ValueError("PDF inválido ou corrompido") from e

    if doc.page_count == 0:
        doc.close()
        raise ValueError("PDF não contém páginas")

    pages: List[Tuple[int, str]] = []
    empty_pages = 0
    total_pages = doc.page_count

    for page_number in range(total_pages):
        page = doc.load_page(page_number)
        text = page.get_text("text")  # type: ignore[attr-defined]
        text = (text or "").strip()

        if not text:
            empty_pages += 1
            logger.debug("Página %d está vazia", page_number + 1)

        pages.append((page_number + 1, text))

    doc.close()

    # Alerta sobre PDFs com muitas páginas vazias (pode ser PDF de imagens)
    if total_pages > 0:
        empty_ratio = empty_pages / total_pages
        if empty_ratio > MAX_EMPTY_PAGES_RATIO:
            logger.warning(
                "PDF tem %.0f%% de páginas vazias (%d/%d) - pode ser PDF de imagens sem OCR",
                empty_ratio * 100, empty_pages, total_pages
            )

    logger.info("Extracted %d pages in %.2fs (%d vazias)", len(pages), time.perf_counter() - start, empty_pages)
    return pages


def prepare_chunks(pages: List[Tuple[int, str]]) -> List[dict]:
    """
    Prepara chunks de texto para embedding.

    Args:
        pages: Lista de tuplas (número_página, texto)

    Returns:
        Lista de dicts com page, chunk_index, text
    """
    prepared: List[dict] = []
    chunk_idx = 0
    skipped = 0

    for page_num, text in pages:
        if not text.strip():
            continue

        for chunk in build_chunks(text):
            # Ignora chunks muito pequenos
            if len(chunk.strip()) < MIN_CHUNK_LENGTH:
                skipped += 1
                continue

            # Valida tamanho do chunk
            tokens = estimate_tokens(chunk)
            if tokens > MAX_INPUT_TOKENS:
                logger.warning(
                    "Chunk %d (página %d) excede limite: %d tokens",
                    chunk_idx, page_num, tokens
                )

            prepared.append(
                {
                    "page": page_num,
                    "chunk_index": chunk_idx,
                    "text": chunk.strip(),
                    "chunk_type": _classify_chunk_type(chunk),
                    "chapter_title": _extract_chapter_title(chunk),
                    "section_title": _extract_section_title(chunk),
                }
            )
            chunk_idx += 1

    if skipped > 0:
        logger.info("Ignorados %d chunks muito pequenos (< %d chars)", skipped, MIN_CHUNK_LENGTH)

    logger.info("Prepared %d chunks from %d pages", len(prepared), len(pages))
    return prepared


def store_chunks(db: Session, document: models.Document, filename: str, chunks: List[dict], embeddings: List[List[float]]):
    """Armazena chunks e embeddings no banco de dados."""
    if len(chunks) != len(embeddings):
        raise ValueError(f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings")

    for chunk, embedding in zip(chunks, embeddings):
        db.add(
            models.Chunk(
                document_id=document.id,
                filename=filename,
                page=chunk["page"],
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                embedding=embedding,
                chunk_type=chunk["chunk_type"],
                chapter_title=chunk.get("chapter_title"),
                section_title=chunk.get("section_title"),
            )
        )
    logger.info("Stored %d chunks for document %s", len(chunks), document.id)


def process_document_inline(db: Session, document: models.Document, pdf_bytes: bytes, filename: str) -> None:
    """
    Processa documento PDF de forma síncrona.

    Args:
        db: Sessão do banco de dados
        document: Modelo do documento
        pdf_bytes: Conteúdo do PDF
        filename: Nome do arquivo

    Raises:
        ValueError: Se o PDF for inválido
        RuntimeError: Se o embedding falhar
    """
    document.status = "processing"
    db.commit()
    logger.info("Processing document %s (%s, %.1f KB)", document.id, filename, len(pdf_bytes) / 1024)
    t0 = time.perf_counter()

    try:
        # 1. Extração de páginas
        pages = extract_pages(pdf_bytes)

        # 2. Preparação de chunks
        chunks = prepare_chunks(pages)

        if not chunks:
            logger.warning("Documento %s não gerou chunks - pode estar vazio ou ser PDF de imagens", document.id)
            document.status = "ready"
            db.commit()
            return

        # 3. Geração de embeddings
        texts = [c["text"] for c in chunks]
        client = OllamaClient()
        logger.info("Requesting embeddings for %d chunks", len(texts))
        embeddings = client.embed(texts)
        logger.info("Received %d embeddings", len(embeddings))

        # 4. Validação dos embeddings
        def _has_signal(vecs):
            return any(any(abs(v) > 1e-9 for v in (vec or [])) for vec in vecs)

        if not embeddings or not _has_signal(embeddings):
            raise RuntimeError("Embeddings are empty or all-zero; check embedding service")

        # 5. Armazenamento
        store_chunks(db, document, filename, chunks, embeddings)
        document.status = "ready"
        db.commit()

        logger.info(
            "Document %s processed successfully in %.2fs (pages=%d, chunks=%d)",
            document.id,
            time.perf_counter() - t0,
            len(pages),
            len(chunks),
        )
    except ValueError as e:
        # Erros de validação (PDF inválido)
        logger.error("Validation error for document %s: %s", document.id, str(e))
        document.status = "failed"
        db.commit()
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Failed to process document %s", document.id)
        document.status = "failed"
        db.commit()
        raise


def process_document_background(document_id: int, pdf_bytes: bytes, filename: str) -> None:
    with SessionLocal() as session:
        document = session.get(models.Document, document_id)
        if not document:
            logger.error("Document %s not found for processing", document_id)
            return
        process_document_inline(session, document, pdf_bytes, filename)
