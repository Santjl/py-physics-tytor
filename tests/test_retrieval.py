from app import models
from app.rag.retrieval import retrieve_chunks


def _add_chunk(db_session, doc, page, chunk_type, chunk_index):
    chunk = models.Chunk(
        document_id=doc.id,
        filename=doc.filename,
        page=page,
        chunk_index=chunk_index,
        text="texto",
        embedding=[0.1] * 768,
        chunk_type=chunk_type,
    )
    db_session.add(chunk)
    return chunk


def test_retrieve_chunks_prefers_theory(db_session):
    doc = models.Document(filename="doc.pdf", status="ready")
    db_session.add(doc)
    db_session.flush()

    _add_chunk(db_session, doc, 1, "exercise", 0)
    _add_chunk(db_session, doc, 2, "theory", 1)
    _add_chunk(db_session, doc, 3, "unknown", 2)
    db_session.commit()

    chunks = retrieve_chunks(db_session, query="teste", top_k=5)
    assert chunks
    assert all(c.chunk_type == "theory" for c in chunks)


def test_retrieve_chunks_falls_back_to_unknown(db_session):
    doc = models.Document(filename="doc2.pdf", status="ready")
    db_session.add(doc)
    db_session.flush()

    _add_chunk(db_session, doc, 1, "exercise", 0)
    _add_chunk(db_session, doc, 2, "unknown", 1)
    db_session.commit()

    chunks = retrieve_chunks(db_session, query="teste", top_k=5)
    assert chunks
    assert all(c.chunk_type == "unknown" for c in chunks)
