from types import SimpleNamespace

from app import models
from app.schemas import FeedbackResponse, PerQuestionFeedback, SimilarExercise, StudyItem
from app.rag import feedback as fb


def _make_chunk(
    chunk_id: int,
    filename: str,
    page: int,
    chapter_title: str | None = None,
    chunk_type: str = "unknown",
) -> models.Chunk:
    return models.Chunk(
        id=chunk_id,
        document_id=1,
        filename=filename,
        page=page,
        chunk_index=chunk_id,
        text="stub",
        embedding=[0.0] * 768,
        chapter_title=chapter_title,
        chunk_type=chunk_type,
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
                    "Raciocinio simulado:\nPensei que A era certo porque confundi\n\n"
                    "Explicacao:\nTexto (S1)\n\n"
                    "Onde estudar no livro:\n- Cinematica (S1)\n\n"
                    "Exercicio similar:\nVeja o exercicio em (E1). Pratica de MRU.\n\n"
                    "Dica:\nRevise as unidades de medida."
                )
            )

    attempt = _build_attempt()
    per_q_chunks = {
        1: [_make_chunk(1, "a.pdf", 1)],
        2: [_make_chunk(2, "b.pdf", 2)],
    }
    ex_chunk = _make_chunk(10, "b.pdf", 5, chunk_type="exercise")
    per_q_exercises = {
        1: [],
        2: [ex_chunk],
    }
    response = fb._generate_feedback_with_llm(FakeLLM(), attempt, per_q_chunks, per_q_exercises)

    assert len(response.per_question) == 2
    pq1 = next(pq for pq in response.per_question if pq.question_id == 1)
    pq2 = next(pq for pq in response.per_question if pq.question_id == 2)
    # pq1 fell back to default
    assert "Revise o conceito" in pq1.explanation
    assert pq1.misconception is not None
    # pq2 was parsed from LLM sections
    assert "Texto" in pq2.explanation
    assert "Explicacao:" not in pq2.explanation
    assert pq2.misconception is not None
    assert "confundi" in pq2.misconception
    assert pq2.similar_question is not None
    assert pq2.similar_question.filename == "b.pdf"
    assert pq2.similar_question.page == 5
    assert pq2.tip is not None


def test_summary_is_computed_in_code():
    attempt = models.Attempt(id=1, score=1.0, total=3)
    summary = fb._build_summary(attempt)
    assert summary.score == 1.0
    assert summary.total == 3
    assert summary.strengths == ["Answered correctly"]
    assert summary.weaknesses == ["Missed questions"]


def test_study_grouping_unique_sorted_pages():
    chunk1 = _make_chunk(1, "a.pdf", 3, chapter_title="Capitulo 1")
    chunk2 = _make_chunk(2, "a.pdf", 1, chapter_title="Capitulo 1")
    chunk3 = _make_chunk(3, "a.pdf", 3, chapter_title="Capitulo 2")
    study = fb._build_study_groups([chunk1, chunk2, chunk3])
    assert any(item.pages == [1, 3] and item.chapter == "Capitulo 1" for item in study)
    assert any(item.pages == [3] and item.chapter == "Capitulo 2" for item in study)


def test_feedback_response_model_validate_passes():
    pq = PerQuestionFeedback(
        question_id=1,
        is_correct=False,
        explanation="Texto",
        misconception="Confundiu A com B",
        tip="Releia o enunciado",
        similar_question=SimilarExercise(filename="a.pdf", page=3, description="Exercicio de cinematica"),
        study=[StudyItem(filename="a.pdf", pages=[1], topic="Cinematica")],
    )
    response = FeedbackResponse(
        attempt_id=1,
        summary=fb._build_summary(models.Attempt(id=1, score=0.0, total=1)),
        per_question=[pq],
        global_references=[],
    )
    validated = FeedbackResponse.model_validate(response.model_dump())
    assert validated.attempt_id == 1
    assert validated.per_question[0].misconception == "Confundiu A com B"
    assert validated.per_question[0].tip == "Releia o enunciado"
    assert validated.per_question[0].similar_question.filename == "a.pdf"
    assert validated.per_question[0].similar_question.page == 3
    assert validated.per_question[0].study[0].topic == "Cinematica"


def test_parse_llm_sections():
    text = (
        "Raciocinio simulado:\nPasso 1, passo 2, erro aqui\n\n"
        "Explicacao:\nO correto e fazer X porque Y (S1)\n\n"
        "Onde estudar no livro:\n- Leis de Newton (S1)\n\n"
        "Exercicio similar:\nVeja o exercicio em (E1). Pratica de dinamica.\n\n"
        "Dica:\nSempre desenhe o diagrama de corpo livre."
    )
    sections = fb._parse_llm_sections(text)
    assert "raciocinio simulado" in sections
    assert "Passo 1" in sections["raciocinio simulado"]
    assert "explicacao" in sections
    assert "O correto" in sections["explicacao"]
    assert "onde estudar no livro" in sections
    assert "Leis de Newton" in sections["onde estudar no livro"]
    assert "exercicio similar" in sections
    assert "E1" in sections["exercicio similar"]
    assert "dica" in sections
    assert "diagrama" in sections["dica"]


def test_parse_llm_sections_legacy_format():
    text = (
        "Explicacao:\nO correto e X\n\n"
        "Possivel confusao:\nConfundiu forca com energia\n\n"
        "Onde estudar no livro:\n- Energia (S1)"
    )
    sections = fb._parse_llm_sections(text)
    assert "possivel confusao" in sections
    assert "Confundiu" in sections["possivel confusao"]
    assert "explicacao" in sections


def test_study_item_topic_from_build_study_groups():
    chunk = _make_chunk(1, "book.pdf", 5, chapter_title="Cap 3")
    study = fb._build_study_groups([chunk], topic_text="- Leis de Newton (S1)")
    assert len(study) == 1
    assert study[0].topic == "Leis de Newton"


def test_default_feedback_populates_new_fields():
    attempt = _build_attempt()
    ans = attempt.answers[0]
    chunks = [_make_chunk(1, "a.pdf", 1)]
    pq = fb._default_per_question_feedback(ans, chunks)
    assert pq.misconception is not None
    assert "raciocinio" in pq.misconception.lower()
    assert pq.tip is not None
    assert "enunciado" in pq.tip.lower()
    assert pq.similar_question is not None
    assert pq.similar_question.filename == "a.pdf"
    assert pq.similar_question.page == 1


def test_summary_perfect_score():
    attempt = models.Attempt(id=1, score=5.0, total=5)
    summary = fb._build_summary(attempt)
    assert summary.strengths == ["Answered correctly"]
    assert summary.weaknesses == []


def test_summary_zero_score():
    attempt = models.Attempt(id=1, score=0.0, total=5)
    summary = fb._build_summary(attempt)
    assert summary.strengths == []
    assert summary.weaknesses == ["Missed questions"]


def test_correct_answers_are_excluded_from_feedback():
    """Only incorrect answers should produce per-question feedback."""
    attempt = _build_attempt()
    # Mark first answer as correct
    attempt.answers[0].is_correct = True
    attempt.score = 1.0

    chunks = [_make_chunk(1, "a.pdf", 1)]
    per_q_chunks = {
        1: chunks,
        2: chunks,
    }

    class FakeLLM:
        def invoke(self, messages):
            return SimpleNamespace(
                content=(
                    "Explicacao:\nTexto\n\n"
                    "Dica:\nRevise."
                )
            )

    response = fb._generate_feedback_with_llm(FakeLLM(), attempt, per_q_chunks)
    assert len(response.per_question) == 1
    assert response.per_question[0].question_id == 2


def test_sanitize_truncates_long_explanation():
    long_text = "A" * 2000
    pq = PerQuestionFeedback(
        question_id=1,
        is_correct=False,
        explanation=long_text,
        misconception="B" * 800,
        tip="C" * 500,
    )
    sanitized = fb._sanitize_per_question_feedback(pq)
    assert len(sanitized.explanation) <= fb.EXPLANATION_MAX_CHARS
    assert len(sanitized.misconception) <= fb.MISCONCEPTION_MAX_CHARS
    assert len(sanitized.tip) <= fb.TIP_MAX_CHARS


def test_extract_similar_exercise_from_exercise_map():
    ex_chunk = _make_chunk(1, "ex.pdf", 7, chunk_type="exercise")
    sections = {"exercicio similar": "Veja o exercicio em (E1). Otimo para treinar."}
    exercise_map = {"E1": ex_chunk}
    result = fb._extract_similar_exercise(
        sections, exercise_map, [ex_chunk],
    )
    assert result is not None
    assert result.filename == "ex.pdf"
    assert result.page == 7


def test_extract_similar_exercise_fallback_to_theory():
    theory_chunk = _make_chunk(1, "book.pdf", 10)
    sections = {"exercicio similar": "Sem exercicios, veja (S1)."}
    source_map = {"S1": theory_chunk}
    result = fb._extract_similar_exercise(
        sections, exercise_map={}, exercise_chunks=[],
        theory_chunks=[theory_chunk], source_map=source_map,
    )
    assert result is not None
    assert result.filename == "book.pdf"
    assert result.page == 10


def test_default_per_question_no_chunks():
    attempt = _build_attempt()
    ans = attempt.answers[0]
    pq = fb._default_per_question_feedback(ans, chunks=[])
    assert "Revise o conceito" in pq.explanation
    assert pq.similar_question is None
    assert pq.study == []
