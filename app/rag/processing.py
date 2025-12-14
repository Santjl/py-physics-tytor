from __future__ import annotations

import logging
from typing import List, Tuple

import fitz
from sqlalchemy.orm import Session

from app import models
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.rag.chunking import build_chunks
from app.rag.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


def extract_pages(pdf_bytes: bytes) -> List[Tuple[int, str]]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: List[Tuple[int, str]] = []
    for page_number in range(doc.page_count):
        page = doc.load_page(page_number)
        text = page.get_text("text")
        pages.append((page_number + 1, text or ""))
    doc.close()
    return pages


def prepare_chunks(pages: List[Tuple[int, str]]) -> List[dict]:
    prepared: List[dict] = []
    chunk_idx = 0
    for page_num, text in pages:
        for chunk in build_chunks(text):
            prepared.append({"page": page_num, "chunk_index": chunk_idx, "text": chunk})
            chunk_idx += 1
    return prepared


def store_chunks(db: Session, document: models.Document, filename: str, chunks: List[dict], embeddings: List[List[float]]):
    for chunk, embedding in zip(chunks, embeddings):
        db.add(
            models.Chunk(
                document_id=document.id,
                filename=filename,
                page=chunk["page"],
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                embedding=embedding,
            )
        )


def process_document_inline(db: Session, document: models.Document, pdf_bytes: bytes, filename: str) -> None:
    document.status = "processing"
    db.commit()
    try:
        pages = extract_pages(pdf_bytes)
        chunks = prepare_chunks(pages)
        texts = [c["text"] for c in chunks] or [""]
        client = OllamaClient()
        embeddings = client.embed(texts)
        store_chunks(db, document, filename, chunks, embeddings)
        document.status = "ready"
        db.commit()
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
