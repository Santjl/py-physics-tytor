"""Pure-Python unit tests for RRF fusion and MMR re-ranking algorithms."""

from types import SimpleNamespace

from app.rag.retrieval import reciprocal_rank_fusion, mmr_rerank


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(chunk_id: int, embedding: list[float], chunk_type: str = "theory"):
    """Create a lightweight object that quacks like models.Chunk for MMR tests."""
    return SimpleNamespace(id=chunk_id, embedding=embedding, chunk_type=chunk_type)


# ---------------------------------------------------------------------------
# RRF tests
# ---------------------------------------------------------------------------

def test_rrf_chunk_in_both_lists_scores_highest():
    semantic = [(1, 1), (2, 2), (3, 3)]
    bm25 = [(2, 1), (3, 2), (4, 3)]
    fused = reciprocal_rank_fusion(semantic, bm25, 0.6, 0.4, k=60)
    ids = [chunk_id for chunk_id, _ in fused]
    # chunk 2 appears in both → highest score
    assert ids[0] == 2


def test_rrf_single_source_semantic_only():
    semantic = [(10, 1), (20, 2)]
    bm25 = []
    fused = reciprocal_rank_fusion(semantic, bm25, 0.6, 0.4, k=60)
    ids = [chunk_id for chunk_id, _ in fused]
    assert ids == [10, 20]


def test_rrf_single_source_bm25_only():
    semantic = []
    bm25 = [(5, 1), (6, 2)]
    fused = reciprocal_rank_fusion(semantic, bm25, 0.6, 0.4, k=60)
    ids = [chunk_id for chunk_id, _ in fused]
    assert ids == [5, 6]


def test_rrf_empty_lists():
    fused = reciprocal_rank_fusion([], [], 0.6, 0.4, k=60)
    assert fused == []


def test_rrf_preserves_all_unique_ids():
    semantic = [(1, 1), (2, 2)]
    bm25 = [(3, 1), (4, 2)]
    fused = reciprocal_rank_fusion(semantic, bm25, 0.6, 0.4, k=60)
    ids = {chunk_id for chunk_id, _ in fused}
    assert ids == {1, 2, 3, 4}


# ---------------------------------------------------------------------------
# MMR tests
# ---------------------------------------------------------------------------

def test_mmr_returns_correct_count():
    chunks = [_make_chunk(i, [float(i)] * 4) for i in range(10)]
    scores = {c.id: 1.0 / (c.id + 1) for c in chunks}
    result = mmr_rerank(chunks, [1.0] * 4, scores, mmr_lambda=0.7, top_k=3)
    assert len(result) == 3


def test_mmr_returns_all_when_fewer_than_top_k():
    chunks = [_make_chunk(1, [1.0, 0.0]), _make_chunk(2, [0.0, 1.0])]
    scores = {1: 0.5, 2: 0.3}
    result = mmr_rerank(chunks, [1.0, 0.0], scores, mmr_lambda=0.7, top_k=5)
    assert len(result) == 2


def test_mmr_empty_input():
    assert mmr_rerank([], [1.0], {}, mmr_lambda=0.7, top_k=3) == []


def test_mmr_lambda_1_equals_pure_relevance():
    c1 = _make_chunk(1, [1.0, 0.0])
    c2 = _make_chunk(2, [0.9, 0.1])
    c3 = _make_chunk(3, [0.0, 1.0])
    scores = {1: 1.0, 2: 0.8, 3: 0.5}
    result = mmr_rerank([c1, c2, c3], [1.0, 0.0], scores, mmr_lambda=1.0, top_k=2)
    result_ids = [c.id for c in result]
    # With lambda=1.0, should pick by pure relevance score order
    assert result_ids == [1, 2]


def test_mmr_promotes_diversity():
    # c1 and c2 are near-duplicates; c3 is very different
    c1 = _make_chunk(1, [1.0, 0.0, 0.0])
    c2 = _make_chunk(2, [0.99, 0.01, 0.0])
    c3 = _make_chunk(3, [0.0, 0.0, 1.0])
    # c1 highest relevance, c2 close second, c3 lower
    scores = {1: 1.0, 2: 0.95, 3: 0.6}
    result = mmr_rerank([c1, c2, c3], [1.0, 0.0, 0.0], scores, mmr_lambda=0.5, top_k=2)
    result_ids = [c.id for c in result]
    # First pick is c1 (highest relevance), second should be c3 (diverse) over c2 (duplicate)
    assert result_ids[0] == 1
    assert result_ids[1] == 3
