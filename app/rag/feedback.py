from __future__ import annotations

import logging
import re
import time
from typing import List, Mapping, Sequence

from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

from app import models
from app.core.config import get_settings
from app.rag.retrieval import retrieve_chunks, retrieve_exercise_chunks
from app.schemas import (
    Citation,
    FeedbackResponse,
    PerQuestionFeedback,
    SimilarExercise,
    StudyItem,
    SummaryFeedback,
)

CHUNK_TEXT_MAX_CHARS = 500
EXPLANATION_MAX_CHARS = 1500
MISCONCEPTION_MAX_CHARS = 600
TIP_MAX_CHARS = 300


logger = logging.getLogger(__name__)


def _format_sources(chunks: Sequence[models.Chunk]) -> str:
    # Importante: para evitar que o LLM copie trechos do livro, não enviamos o texto.
    # Enviamos apenas metadados (arquivo/página) para ele usar como referência.
    lines: list[str] = []
    for chunk in chunks:
        lines.append(f"[SOURCE: {chunk.filename} p.{chunk.page} id={chunk.id}]")
    return "\n".join(lines)


def _build_system_prompt() -> str:
    return (
        "You are a physics specialist assistant that produces ONLY valid JSON for quiz feedback.\n"
        "\n"
        "CRITICAL OUTPUT RULES:\n"
        "- Output MUST be a single JSON object (no markdown, no extra text).\n"
        "- Top-level JSON keys MUST be exactly: attempt_id, summary, per_question, global_references.\n"
        "- Do NOT output keys like 'question1', 'question2'. per_question MUST be a LIST.\n"
        "- per_question MUST contain ONLY questions answered incorrectly (is_correct=false).\n"
        "\n"
        "CITATION RULES:\n"
        "- You MUST cite sources strictly from the provided chunks.\n"
        "- Do NOT invent citations.\n"
        "- Citations must include ONLY: filename and page.\n"
        "- Do NOT quote or copy text from the book. Do NOT include long excerpts.\n"
        "- Do NOT include any direct quotes (no quotation marks). Paraphrase in your own words.\n"
        "- Never copy more than a short phrase from any source.\n"
        "- If no relevant source exists for a question, set citations=[] and explicitly say no relevant source was found.\n"
        "\n"
        "FEEDBACK CONTENT RULES:\n"
        "- Provide feedback ONLY for incorrect answers.\n"
        "- Explain WHY the student's reasoning is wrong and what the correct reasoning is, using the book pages only as grounding.\n"
        "- Explanations must be written in your own words, concise, and actionable.\n"
        "\n"
        "OUTPUT JSON SCHEMA:\n"
        "{\n"
        '  \"attempt_id\": <int>,\n'
        '  \"summary\": {\"score\": <number>, \"total\": <int>, \"strengths\": [<string>], \"weaknesses\": [<string>]},\n'
        '  \"per_question\": [\n'
        "    {\n"
        '      \"question_id\": <int>,\n'
        '      \"is_correct\": <true|false>,\n'
        '      \"explanation\": <string>,\n'
        '      \"study\": [\n'
        "        {\n"
        '          \"filename\": <string>,\n'
        '          \"pages\": [<int>],\n'
        '          \"chapter\": <string|null>\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  \"global_references\": [ {\"filename\": <string>, \"page\": <int>} ]\n'
        "}\n"
    )


def _build_user_prompt(attempt: models.Attempt, chunks: Sequence[models.Chunk]) -> str:
    qa: list[str] = []
    for answer in attempt.answers:
        qa.append(
            f"Q{answer.question_id}: {answer.question.statement}\n"
            f"Selected: {answer.option.letter} - {answer.option.text}\n"
            f"Correct: {answer.is_correct}"
        )
    qa_block = "\n\n".join(qa)
    sources = _format_sources(chunks) if chunks else "No relevant source found in uploaded materials."
    return (
        f"Attempt score {attempt.score}/{attempt.total}. Provide feedback.\n"
        f"Answers:\n{qa_block}\n\n"
        f"Sources:\n{sources}\n"
        "Use citations strictly from the sources. If none, set citations=[] and state no relevant source."
    )


def _build_user_prompt_per_question(
    attempt: models.Attempt,
    per_q_chunks: Mapping[int, Sequence[models.Chunk]],
) -> str:
    blocks: list[str] = []

    for ans in attempt.answers:
        if ans.is_correct:
            continue

        chunks = per_q_chunks.get(ans.question_id, [])
        sources = _format_sources(chunks) if chunks else "No relevant source found in uploaded materials."

        correct_opt = next((o for o in ans.question.options if o.is_correct), None)
        correct_txt = f"{correct_opt.letter} - {correct_opt.text}" if correct_opt else "Unknown"
        selected_txt = f"{ans.option.letter} - {ans.option.text}"

        blocks.append(
            f"Q{ans.question_id}: {ans.question.statement}\n"
            f"Selected: {selected_txt}\n"
            f"Correct option: {correct_txt}\n"
            f"Is correct: {ans.is_correct}\n"
            f"Sources:\n{sources}\n"
        )

    return (
        f"Attempt score {attempt.score}/{attempt.total}. Provide feedback.\n\n"
        + "\n---\n".join(blocks)
        + "\n\nRules: Provide feedback ONLY for the incorrect questions shown. "
        "Use citations strictly from the sources shown under each question. "
        "If a question has no sources, set citations=[] and explicitly state no relevant source was found. "
        "Return citations with only filename/page (no snippet)."
    )


def build_system_prompt_per_question() -> str:
    return (
        "Voce e um assistente especialista em fisica. Responda em PT-BR, em tom de conversa.\n"
        "Nao use Markdown.\n"
        "\n"
        "SEU OBJETIVO:\n"
        "- Explicar o raciocinio correto ESPECIFICO para esta questao (nao generalize).\n"
        "- Deduzir qual foi o erro conceitual ou raciocinio equivocado do aluno.\n"
        "- Indicar onde no material o aluno pode estudar o tema.\n"
        "- Indicar um exercicio similar do proprio material, se fornecido.\n"
        "- Dar dicas praticas de melhoria.\n"
        "\n"
        "REGRA CRITICA SOBRE A EXPLICACAO:\n"
        "- A explicacao DEVE ser especifica para o cenario da questao.\n"
        "- Analise os dados concretos do enunciado (valores, condicoes, geometria).\n"
        "- Aplique formulas e conceitos ao caso PARTICULAR da questao.\n"
        "- NAO diga apenas que um teorema se aplica; mostre COMO e POR QUE ele se aplica neste caso.\n"
        "- Se uma formula so vale em condicoes especificas (ex: velocidades perpendiculares), "
        "explique essa condicao e por que ela existe nesta questao.\n"
        "- Apos a explicacao especifica, voce pode acrescentar 1-2 frases de contexto conceitual geral.\n"
        "\n"
        "REQUISITOS DE CONCISAO:\n"
        f"- Explicacao (raciocinio correto) <= {EXPLANATION_MAX_CHARS} caracteres.\n"
        f"- Erro conceitual <= {MISCONCEPTION_MAX_CHARS} caracteres.\n"
        f"- Dica <= {TIP_MAX_CHARS} caracteres.\n"
        "- NUNCA gere mais de 1 item em 'Onde estudar no livro'; una ideias em um unico item.\n"
        "\n"
        "REGRAS DE CITACAO:\n"
        "- Use APENAS os identificadores fornecidos (S1..Sk e E1..Ek).\n"
        "- Cite fontes somente como (S1), (E1), etc.\n"
        "- Nao invente IDs.\n"
        "- Nao escreva numeros de pagina.\n"
        "\n"
        "FORMATO OBRIGATORIO (use exatamente estes cabecalhos):\n"
        "Explicacao:\n"
        "<3-6 frases detalhando passo a passo como chegar na resposta correta NESTA questao. "
        "Referencie os dados do enunciado. Mostre as formulas aplicadas ao caso concreto. "
        "Depois, opcionalmente, 1-2 frases de contexto conceitual geral>\n"
        "\n"
        "Erro conceitual do aluno:\n"
        "<2-4 frases analisando a resposta marcada pelo aluno e deduzindo qual raciocinio "
        "ou confusao conceitual pode te-lo levado a essa escolha. Se nao houver um raciocinio "
        "plausivel, diga que provavelmente foi um chute ou desatencao>\n"
        "\n"
        "Onde estudar no livro:\n"
        "- <topico e capitulo onde o aluno encontrara teoria sobre o tema> (S1)\n"
        "\n"
        "Exercicio similar:\n"
        "<Se foram fornecidos exercicios do material (E1..Ek), indique qual deles e mais "
        "proximo ao conceito desta questao e descreva brevemente por que e relevante. "
        "Use o formato: Veja o exercicio em (E1). "
        "Nao precisa ser exatamente o mesmo assunto, pode ser um exercicio parecido ou "
        "que envolva conceitos semelhantes (ex: velocidade relativa, vetores, etc). "
        "Se nao houver exercicios fornecidos (E1..Ek), indique a fonte teorica (S1..Sk) "
        "mais relevante e sugira que o aluno procure exercicios proximo a essa pagina. "
        "Use o formato: Procure exercicios semelhantes proximo a (S1).>\n"
        "\n"
        "Dica:\n"
        "<1-2 frases com dica pratica para o aluno evitar esse tipo de erro no futuro>\n"
        "\n"
        "Se nao houver fontes relevantes, diga isso explicitamente e nao cite IDs."
    )


def build_user_prompt_for_question(
    ans: models.Answer,
    chunks: Sequence[models.Chunk],
    exercise_chunks: Sequence[models.Chunk] | None = None,
) -> tuple[str, dict[str, models.Chunk], dict[str, models.Chunk]]:
    """Build the user prompt for a single question.

    Returns (prompt, theory_source_map, exercise_source_map).
    """
    source_map: dict[str, models.Chunk] = {}
    source_lines: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        sid = f"S{idx}"
        source_map[sid] = chunk
        source_lines.append(f"{sid}: filename={chunk.filename}; page={chunk.page}; chunk_id={chunk.id}")

    sources_block = "\n".join(source_lines) if source_lines else "Sem fontes relevantes."

    exercise_map: dict[str, models.Chunk] = {}
    exercise_lines: list[str] = []
    for idx, chunk in enumerate(exercise_chunks or [], start=1):
        eid = f"E{idx}"
        exercise_map[eid] = chunk
        exercise_lines.append(f"{eid}: filename={chunk.filename}; page={chunk.page}; chunk_id={chunk.id}")

    exercises_block = (
        "\n".join(exercise_lines) if exercise_lines
        else "Nenhum exercicio encontrado no material."
    )

    correct_opt = next((o for o in ans.question.options if o.is_correct), None)
    correct_txt = f"{correct_opt.letter} - {correct_opt.text}" if correct_opt else "Desconhecida"
    selected_txt = f"{ans.option.letter} - {ans.option.text}"

    prompt = (
        f"Q{ans.question_id}: {ans.question.statement}\n"
        f"Resposta escolhida: {selected_txt}\n"
        f"Resposta correta: {correct_txt}\n"
        "\n"
        "Fontes teoricas (use apenas os IDs S1..Sk; nao inclua numeros de pagina):\n"
        f"{sources_block}\n"
        "\n"
        "Exercicios do material (use apenas os IDs E1..Ek):\n"
        f"{exercises_block}\n"
    )
    return prompt, source_map, exercise_map


# Section headers the LLM may use (normalised to lowercase for matching).
_SECTION_HEADERS = [
    "explicacao",
    "raciocinio correto",
    "raciocinio simulado",
    "erro conceitual do aluno",
    "erro conceitual",
    "possivel confusao",
    "onde estudar no livro",
    "questao similar",
    "exercicio similar",
    "dica",
    "dicas",
]

_SECTION_HEADER_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(h) for h in _SECTION_HEADERS) + r")\s*:\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_llm_sections(text: str) -> dict[str, str]:
    """Split LLM output into named sections.

    Returns a dict keyed by the *lowercased* header name with content as value.
    """
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        # Check if this line is a section header
        colon_idx = stripped.find(":")
        if colon_idx > 0:
            candidate = stripped[:colon_idx].strip().lower()
            rest_after_colon = stripped[colon_idx + 1:].strip()
            if candidate in _SECTION_HEADERS:
                # Save previous section
                if current_key is not None:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = candidate
                # If the header line has content after the colon, keep it
                current_lines = [rest_after_colon] if rest_after_colon else []
                continue
        if current_key is not None:
            current_lines.append(line)

    # Save last section
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def invoke_llm_for_question(llm, system_prompt: str, user_prompt: str) -> str:
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    result = llm.invoke(messages)
    return result.content if isinstance(result.content, str) else str(result.content)


def extract_source_ids(text: str, valid_ids: set[str]) -> list[str]:
    if not text or not valid_ids:
        return []
    found = re.findall(r"\bS\d+\b", text)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in found:
        if item in valid_ids and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def map_source_ids_to_chunks(
    ids: Sequence[str],
    source_map: Mapping[str, models.Chunk],
) -> list[models.Chunk]:
    chunks: list[models.Chunk] = []
    for sid in ids:
        chunk = source_map.get(sid)
        if not chunk:
            continue
        chunks.append(chunk)
    return chunks


def _truncate_chars(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _sanitize_study_items(study: Sequence[StudyItem]) -> list[StudyItem]:
    sanitized: list[StudyItem] = []
    for item in study:
        pages = sorted(set(item.pages))
        chapter = item.chapter if item.chapter else None
        topic = item.topic if item.topic else None
        sanitized.append(
            StudyItem(
                filename=item.filename,
                pages=pages,
                chapter=chapter,
                topic=topic,
            )
        )
    return sanitized


def _sanitize_per_question_feedback(pq: PerQuestionFeedback) -> PerQuestionFeedback:
    explanation = _truncate_chars(pq.explanation or "", EXPLANATION_MAX_CHARS)
    misconception = _truncate_chars(pq.misconception or "", MISCONCEPTION_MAX_CHARS) if pq.misconception else None
    tip = _truncate_chars(pq.tip or "", TIP_MAX_CHARS) if pq.tip else None
    study = _sanitize_study_items(pq.study)
    return PerQuestionFeedback(
        question_id=pq.question_id,
        is_correct=pq.is_correct,
        explanation=explanation,
        misconception=misconception,
        tip=tip,
        similar_question=pq.similar_question,
        study=study,
    )


def _extract_topic_from_text(text: str) -> str | None:
    """Extract the topic name from 'Onde estudar no livro' text, stripping source IDs."""
    if not text:
        return None
    # Remove leading '- ' bullets
    cleaned = re.sub(r"^\s*-\s*", "", text.strip())
    # Remove source references like (S1), (S2)
    cleaned = re.sub(r"\(S\d+\)", "", cleaned).strip()
    # Take only the first line (the actual topic)
    first_line = cleaned.split("\n")[0].strip()
    return first_line if first_line else None


def _build_study_groups(
    chunks: Sequence[models.Chunk],
    topic_text: str | None = None,
) -> list[StudyItem]:
    topic = _extract_topic_from_text(topic_text)

    grouped: dict[tuple[str, str | None], set[int]] = {}
    for chunk in chunks:
        key = (chunk.filename, chunk.chapter_title)
        grouped.setdefault(key, set()).add(chunk.page)

    study_items: list[StudyItem] = []
    for (filename, chapter_title), pages in grouped.items():
        study_items.append(
            StudyItem(
                filename=filename,
                chapter=chapter_title or None,
                pages=sorted(pages),
                topic=topic,
            )
        )
    return _sanitize_study_items(study_items)


def _default_feedback(attempt: models.Attempt, chunks: Sequence[models.Chunk]) -> FeedbackResponse:
    per_question = [
        _sanitize_per_question_feedback(_default_per_question_feedback(ans, chunks))
        for ans in attempt.answers
        if not ans.is_correct
    ]
    summary = _build_summary(attempt)
    citation_items = _collect_global_references(per_question)
    return FeedbackResponse(
        attempt_id=attempt.id,
        summary=summary,
        per_question=per_question,
        global_references=citation_items[:8],
    )


def _strip_where_to_study(text: str) -> str:
    lower = text.lower()
    marker = "onde estudar no livro:"
    idx = lower.find(marker)
    if idx == -1:
        return text.strip()
    return text[:idx].strip()


def _build_summary(attempt: models.Attempt) -> SummaryFeedback:
    score = attempt.score or 0.0
    total = attempt.total or 0
    return SummaryFeedback(
        score=score,
        total=total,
        strengths=["Answered correctly"] if score > 0 else [],
        weaknesses=["Missed questions"] if score < total else [],
    )


def _default_per_question_feedback(
    ans: models.Answer,
    chunks: Sequence[models.Chunk],
) -> PerQuestionFeedback:
    explanation = "Revise o conceito e compare com as fontes indicadas." if chunks else "Revise o conceito."
    misconception = "Nao foi possivel determinar o raciocinio do aluno automaticamente."
    tip = "Releia o enunciado com atencao e confira as unidades."
    study = _build_study_groups(chunks[:4]) if chunks else []

    similar_question: SimilarExercise | None = None
    if chunks:
        similar_question = SimilarExercise(
            filename=chunks[0].filename,
            page=chunks[0].page,
            description="Procure exercicios sobre este tema proximo a esta pagina no material.",
        )

    return PerQuestionFeedback(
        question_id=ans.question_id,
        is_correct=ans.is_correct,
        explanation=explanation,
        misconception=misconception,
        tip=tip,
        similar_question=similar_question,
        study=study,
    )


def _collect_global_references(per_question: Sequence[PerQuestionFeedback]) -> list[Citation]:
    global_refs: list[Citation] = []
    seen: set[tuple[str, int]] = set()
    for pq in per_question:
        for study in pq.study:
            for page in study.pages:
                key = (study.filename, page)
                if key in seen:
                    continue
                seen.add(key)
                global_refs.append(Citation(filename=study.filename, page=page, snippet=""))
    return global_refs


def _truncate_text(text: str, limit: int = 300) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _retrieval_query_for_answer(ans: models.Answer) -> str:
    correct_opt = next((o for o in ans.question.options if o.is_correct), None)
    correct_txt = f"{correct_opt.letter} - {correct_opt.text}" if correct_opt else "Unknown"
    selected_txt = f"{ans.option.letter} - {ans.option.text}"

    return (
        f"{ans.question.statement}\n"
        f"Selected: {selected_txt}\n"
        f"Correct option: {correct_txt}"
    )


def _retrieve_per_question(
    db,
    attempt: models.Attempt,
    top_k: int = 4,
    exercise_top_k: int = 2,
) -> tuple[Mapping[int, Sequence[models.Chunk]], Mapping[int, Sequence[models.Chunk]]]:
    """Retrieve theory and exercise chunks per incorrect question.

    Returns (per_q_theory, per_q_exercises).
    """
    per_q: dict[int, list[models.Chunk]] = {}
    per_q_ex: dict[int, list[models.Chunk]] = {}
    for ans in attempt.answers:
        if ans.is_correct:
            continue
        q = _retrieval_query_for_answer(ans)
        per_q[ans.question_id] = list(retrieve_chunks(db, query=q, top_k=top_k))
        per_q_ex[ans.question_id] = list(
            retrieve_exercise_chunks(db, query=q, top_k=exercise_top_k),
        )
    return per_q, per_q_ex


def _default_feedback_from_per_q(
    attempt: models.Attempt,
    per_q_chunks: Mapping[int, Sequence[models.Chunk]],
) -> FeedbackResponse:
    per_question: List[PerQuestionFeedback] = []

    for ans in attempt.answers:
        if ans.is_correct:
            continue

        chunks = per_q_chunks.get(ans.question_id, [])
        per_question.append(_sanitize_per_question_feedback(_default_per_question_feedback(ans, chunks)))

    summary = _build_summary(attempt)
    global_refs = _collect_global_references(per_question)
    return FeedbackResponse(
        attempt_id=attempt.id,
        summary=summary,
        per_question=per_question,
        global_references=global_refs[:8],
    )


def _extract_explanation(sections: dict[str, str]) -> str:
    """Pick the best section for the 'explanation' field."""
    for key in ("explicacao", "raciocinio correto"):
        if key in sections:
            return sections[key]
    return ""


def _extract_misconception(sections: dict[str, str]) -> str | None:
    for key in ("erro conceitual do aluno", "erro conceitual", "possivel confusao", "raciocinio simulado"):
        if key in sections:
            return sections[key]
    return None


def _extract_similar_exercise(
    sections: dict[str, str],
    exercise_map: dict[str, models.Chunk],
    exercise_chunks: Sequence[models.Chunk],
    theory_chunks: Sequence[models.Chunk] | None = None,
    source_map: dict[str, models.Chunk] | None = None,
) -> SimilarExercise | None:
    """Build a SimilarExercise from the LLM 'exercicio similar' section.

    Priority:
    1. Exercise chunk cited by LLM (E1..Ek)
    2. First available exercise chunk
    3. Theory source cited by LLM in this section (S1..Sk)
    4. First available theory chunk (generic fallback)
    """
    text = sections.get("exercicio similar") or sections.get("questao similar") or ""

    # 1. Try to find an exercise ID cited by the LLM
    cited_eids = re.findall(r"\bE\d+\b", text)
    for eid in cited_eids:
        chunk = exercise_map.get(eid)
        if chunk:
            description = re.sub(r"\([ES]\d+\)", "", text).strip() or None
            return SimilarExercise(
                filename=chunk.filename,
                page=chunk.page,
                description=description,
            )

    # 2. Fallback: use first available exercise chunk
    if exercise_chunks:
        chunk = exercise_chunks[0]
        description = text if text and "nenhum" not in text.lower() else None
        return SimilarExercise(
            filename=chunk.filename,
            page=chunk.page,
            description=description,
        )

    # 3. Fallback: check if LLM cited a theory source (S-id) in this section
    if source_map and text:
        cited_sids = re.findall(r"\bS\d+\b", text)
        for sid in cited_sids:
            chunk = source_map.get(sid)
            if chunk:
                description = re.sub(r"\([ES]\d+\)", "", text).strip() or None
                return SimilarExercise(
                    filename=chunk.filename,
                    page=chunk.page,
                    description=description,
                )

    # 4. Fallback: use theory chunks to suggest a page with related content
    if theory_chunks:
        chunk = theory_chunks[0]
        description = (
            "Nenhum exercicio foi localizado automaticamente, mas voce pode "
            "encontrar problemas semelhantes proximo a esta pagina no material."
        )
        return SimilarExercise(
            filename=chunk.filename,
            page=chunk.page,
            description=description,
        )

    return None


def _extract_tip(sections: dict[str, str]) -> str | None:
    return sections.get("dica") or sections.get("dicas")


def _extract_study_text(sections: dict[str, str]) -> str | None:
    return sections.get("onde estudar no livro")


def _generate_feedback_with_llm(
    llm,
    attempt: models.Attempt,
    per_q_chunks: Mapping[int, Sequence[models.Chunk]],
    per_q_exercises: Mapping[int, Sequence[models.Chunk]] | None = None,
) -> FeedbackResponse:
    system_prompt = build_system_prompt_per_question()
    per_question: list[PerQuestionFeedback] = []
    per_q_exercises = per_q_exercises or {}

    for ans in attempt.answers:
        if ans.is_correct:
            continue

        chunks = per_q_chunks.get(ans.question_id, [])
        exercise_chunks = per_q_exercises.get(ans.question_id, [])
        user_prompt, source_map, exercise_map = build_user_prompt_for_question(
            ans, chunks, exercise_chunks,
        )
        fallback = False
        t1 = time.perf_counter()

        try:
            text = invoke_llm_for_question(llm, system_prompt, user_prompt)
            logger.info("LLM raw (truncated): %r", _truncate_text(text, limit=500))

            # Parse structured sections
            sections = _parse_llm_sections(text)

            # Extract source IDs from the full text (S-ids for theory)
            ids = extract_source_ids(text, set(source_map.keys()))
            cited_chunks = map_source_ids_to_chunks(ids, source_map)
            study_chunks = cited_chunks if cited_chunks else chunks

            # Build each field from parsed sections
            explanation = _extract_explanation(sections)
            if not explanation:
                explanation = _strip_where_to_study(text)

            misconception = _extract_misconception(sections)
            similar_question = _extract_similar_exercise(
                sections, exercise_map, exercise_chunks,
                theory_chunks=chunks, source_map=source_map,
            )
            tip = _extract_tip(sections)
            study_text = _extract_study_text(sections)
            study = _build_study_groups(study_chunks, topic_text=study_text)

            pq = PerQuestionFeedback(
                question_id=ans.question_id,
                is_correct=False,
                explanation=explanation,
                misconception=misconception,
                tip=tip,
                similar_question=similar_question,
                study=study,
            )
            per_question.append(_sanitize_per_question_feedback(pq))
        except Exception:  # noqa: BLE001
            fallback = True
            logger.exception("LLM failed for question %d, falling back", ans.question_id)
            per_question.append(_sanitize_per_question_feedback(_default_per_question_feedback(ans, chunks)))
        finally:
            logger.info(
                "llm.invoke.question: %.2fs (question_id=%d fallback=%s)",
                time.perf_counter() - t1,
                ans.question_id,
                fallback,
            )

    summary = _build_summary(attempt)
    global_refs = _collect_global_references(per_question)[:8]
    return FeedbackResponse(
        attempt_id=attempt.id,
        summary=summary,
        per_question=per_question,
        global_references=global_refs,
    )


def generate_feedback(db, attempt: models.Attempt, query: str = "physics study tips") -> FeedbackResponse:
    settings = get_settings()

    # retrieval por questão (melhora diversidade das citações)
    t0 = time.perf_counter()
    per_q_chunks, per_q_exercises = _retrieve_per_question(db, attempt, top_k=4, exercise_top_k=2)
    incorrect_count = sum(1 for ans in attempt.answers if not ans.is_correct)
    logger.info(
        "retrieve_per_question: %.2fs (questions=%d)",
        time.perf_counter() - t0,
        incorrect_count,
    )

    if settings.app_env.lower() == "test":
        return _default_feedback_from_per_q(attempt, per_q_chunks)

    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_chat_model,
        temperature=0.0,
    )

    try:
        return _generate_feedback_with_llm(llm, attempt, per_q_chunks, per_q_exercises)
    except Exception:  # noqa: BLE001
        logger.exception("Feedback generation failed, falling back to default")
        return _default_feedback_from_per_q(attempt, per_q_chunks)
