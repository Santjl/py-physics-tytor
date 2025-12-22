from types import SimpleNamespace

from app import models
from app.schemas import FeedbackResponse, PerQuestionFeedback, StudyItem
from app.rag import feedback as fb


def _make_chunk(chunk_id: int, filename: str, page: int) -> models.Chunk:
    return models.Chunk(
        id=chunk_id,
        document_id=1,
        filename=filename,
        page=page,
        chunk_index=chunk_id,
        text="stub",
        embedding=[0.0] * 768,
    )


def _build_attempt() -> models.Attempt:
    q1 = models.Question(id=1, statement="Q1", questionnaire_id=1)
    q1a = models.Option(id=1, question_id=1, letter="A", text="wrong", is_correct=False)
    q1b = models.Option(id=2, question_id=1, letter="B", text="right", is_correct=True)
    q1.options = [q1a, q1b]

    q2 = models.Question(id=2, statement="Q2", questionnaire_id=1)
    q2a = models.Option(id=3, question_id=2, letter="A", text="wrong", is_correct=False)
    q2b = models.Option(id=4, question_id=2, letter="B", text="right", is_correct=True)
    q2.options = [q2a, q2b]

    a1 = models.Answer(
        id=1,
        attempt_id=1,
        question_id=1,
        selected_option_id=1,
        is_correct=False,
    )
    a1.option = q1a
    a1.question = q1

    a2 = models.Answer(
        id=2,
        attempt_id=1,
        question_id=2,
        selected_option_id=3,
        is_correct=False,
    )
    a2.option = q2a
    a2.question = q2

    attempt = models.Attempt(id=1, score=0.0, total=2)
    attempt.answers = [a1, a2]
    return attempt


def test_extract_source_ids_and_mapping():
    chunk1 = _make_chunk(1, "book.pdf", 10)
    chunk2 = _make_chunk(2, "notes.pdf", 20)
    source_map = {"S1": chunk1, "S2": chunk2}

    text = "Veja (S2) e (S1) e (S2)."
    ids = fb.extract_source_ids(text, set(source_map.keys()))
    assert ids == ["S2", "S1"]

    chunks = fb.map_source_ids_to_chunks(ids, source_map)
    assert [(c.filename, c.page) for c in chunks] == [("notes.pdf", 20), ("book.pdf", 10)]


def test_extract_source_ids_ignores_unknown():
    chunk1 = _make_chunk(1, "book.pdf", 10)
    source_map = {"S1": chunk1}
    ids = fb.extract_source_ids("Nada (S9) e (S1).", set(source_map.keys()))
    assert ids == ["S1"]


def test_per_question_fallback_does_not_break_response():
    class FakeLLM:
        def invoke(self, messages):
            user_prompt = messages[-1].content
            if "Q1:" in user_prompt:
                raise RuntimeError("boom")
            return SimpleNamespace(
                content=(
                    "Explicacao:\nTexto (S1)\n\n"
                    "Possivel confusao:\nAlgo\n\n"
                    "Onde estudar no livro:\n- Topico (S1)"
                )
            )

    attempt = _build_attempt()
    per_q_chunks = {
        1: [_make_chunk(1, "a.pdf", 1)],
        2: [_make_chunk(2, "b.pdf", 2)],
    }
    response = fb._generate_feedback_with_llm(FakeLLM(), attempt, per_q_chunks)

    assert len(response.per_question) == 2
    pq1 = next(pq for pq in response.per_question if pq.question_id == 1)
    pq2 = next(pq for pq in response.per_question if pq.question_id == 2)
    assert "Revise o conceito" in pq1.explanation
    assert "Explicacao:" in pq2.explanation


def test_summary_is_computed_in_code():
    attempt = models.Attempt(id=1, score=1.0, total=3)
    summary = fb._build_summary(attempt)
    assert summary.score == 1.0
    assert summary.total == 3
    assert summary.strengths == ["Answered correctly"]
    assert summary.weaknesses == ["Missed questions"]


def test_study_grouping_unique_sorted_pages():
    chunk1 = _make_chunk(1, "a.pdf", 3)
    chunk2 = _make_chunk(2, "a.pdf", 1)
    chunk3 = _make_chunk(3, "a.pdf", 3)
    chunk1.chapter_title = "Capitulo 1"
    chunk2.chapter_title = "Capitulo 1"
    chunk3.chapter_title = "Capitulo 2"
    study = fb._build_study_groups([chunk1, chunk2, chunk3])
    assert any(item.pages == [1, 3] and item.chapter == "Capitulo 1" for item in study)


def test_feedback_response_model_validate_passes():
    pq = PerQuestionFeedback(
        question_id=1,
        is_correct=False,
        explanation="Texto",
        study=[StudyItem(filename="a.pdf", pages=[1])],
    )
    response = FeedbackResponse(
        attempt_id=1,
        summary=fb._build_summary(models.Attempt(id=1, score=0.0, total=1)),
        per_question=[pq],
        global_references=[],
    )
    validated = FeedbackResponse.model_validate(response.model_dump())
    assert validated.attempt_id == 1
