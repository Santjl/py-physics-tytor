import logging
import re
from typing import List

logger = logging.getLogger(__name__)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Aproximação: 1 token ≈ 4 caracteres para inglês/português
CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS = 256  # ~1024 caracteres
DEFAULT_OVERLAP_TOKENS = 50  # ~200 caracteres
MAX_INPUT_TOKENS = 8192  # Limite do nomic-embed-text


def estimate_tokens(text: str) -> int:
    """Estima número de tokens baseado em caracteres."""
    return len(text) // CHARS_PER_TOKEN


def split_paragraphs(text: str) -> List[str]:
    """Divide texto em parágrafos baseado em linhas vazias."""
    paragraphs: List[str] = []
    buffer: List[str] = []
    for line in text.splitlines():
        if line.strip():
            buffer.append(line.strip())
        else:
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
    if buffer:
        paragraphs.append(" ".join(buffer))
    return paragraphs


def _safe_tail(s: str, overlap_chars: int) -> str:
    """Extrai cauda do texto para overlap, evitando cortar palavras."""
    if overlap_chars <= 0 or not s:
        return ""
    tail = s[-overlap_chars:]
    # Tenta começar em boundary de palavra
    i = tail.find(" ")
    if 0 < i < len(tail) - 1:
        tail = tail[i + 1:]
    return tail.strip()


def _split_by_sentences(text: str, max_chars: int) -> List[str]:
    """Divide texto por sentenças respeitando limite de caracteres."""
    sentences = _SENT_SPLIT.split(text)
    chunks: List[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if not current:
            current = sentence
            continue

        if len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks


def _split_long_paragraph(para: str, max_chunk_chars: int) -> List[str]:
    """Divide parágrafo longo em chunks menores."""
    if len(para) <= max_chunk_chars:
        return [para]

    # Primeiro tenta dividir por sentenças
    chunks = _split_by_sentences(para, max_chunk_chars)

    # Fallback: se ainda tiver pedaço gigante (sem pontuação), corta por palavras
    final: List[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chunk_chars:
            final.append(chunk)
        else:
            # Divide por palavras para não cortar no meio
            words = chunk.split()
            current = ""
            for word in words:
                if not current:
                    current = word
                elif len(current) + 1 + len(word) <= max_chunk_chars:
                    current = f"{current} {word}"
                else:
                    final.append(current)
                    current = word
            if current:
                final.append(current)

    return final


def build_chunks(
    text: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> List[str]:
    """
    Constrói chunks de texto com overlap para embedding.

    Args:
        text: Texto a ser dividido
        max_tokens: Máximo de tokens por chunk (estimado)
        overlap_tokens: Tokens de overlap entre chunks

    Returns:
        Lista de chunks de texto
    """
    max_chunk_chars = max_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        for piece in _split_long_paragraph(para, max_chunk_chars):
            if not current:
                current = piece
                continue

            if len(current) + 1 + len(piece) > max_chunk_chars:
                chunks.append(current)
                tail = _safe_tail(current, overlap_chars)
                current = f"{tail} {piece}".strip() if tail else piece
            else:
                current = f"{current} {piece}".strip()

    if current:
        chunks.append(current)

    # Validação: avisar se algum chunk excede limite do modelo
    for i, chunk in enumerate(chunks):
        tokens = estimate_tokens(chunk)
        if tokens > MAX_INPUT_TOKENS:
            logger.warning(
                "Chunk %d excede limite do modelo (%d tokens > %d)",
                i, tokens, MAX_INPUT_TOKENS
            )

    logger.debug("Gerados %d chunks (max_tokens=%d, overlap=%d)", len(chunks), max_tokens, overlap_tokens)
    return chunks
