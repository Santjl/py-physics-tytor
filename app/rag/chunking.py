from __future__ import annotations

from typing import Iterable, List


def split_paragraphs(text: str) -> List[str]:
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


def build_chunks(text: str, max_chunk_size: int = 900, overlap: int = 150) -> List[str]:
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) + 1 > max_chunk_size and current:
            chunks.append(" ".join(current))
            # start new chunk with overlap from last chunk
            if overlap > 0 and chunks[-1]:
                tail = chunks[-1][-overlap:]
                current = [tail]
                current_len = len(tail)
            else:
                current = []
                current_len = 0
        current.append(para)
        current_len += len(para) + 1

    if current:
        chunks.append(" ".join(current))

    return chunks
