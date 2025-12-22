from __future__ import annotations

import logging
import re
import time
from typing import List, Mapping, Sequence

from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

from app import models
from app.core.config import get_settings
from app.rag.retrieval import retrieve_chunks
from app.schemas import (
    Citation,
    FeedbackResponse,
    PerQuestionFeedback,
    StudyItem,
    SummaryFeedback,
)

CHUNK_TEXT_MAX_CHARS = 500
EXPLANATION_MAX_CHARS = 700
MISCONCEPTION_MAX_CHARS = 250
TIP_MAX_CHARS = 120


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
        "REQUISITOS DE CONCISAO:\n"
        f"- Explicacao <= {EXPLANATION_MAX_CHARS} caracteres.\n"
        f"- Possivel confusao <= {MISCONCEPTION_MAX_CHARS} caracteres.\n"
        f"- Se incluir Dicas de melhoria: 2-3 bullets, cada <= {TIP_MAX_CHARS} caracteres.\n"
        "- NUNCA gere mais de 1 item em 'Onde estudar no livro'; una ideias em um unico item.\n"
        "\n"
        "REGRAS DE CITACAO:\n"
        "- Use APENAS os identificadores fornecidos (S1..Sk).\n"
        "- Cite fontes somente como (S1), (S2), etc.\n"
        "- Nao invente IDs.\n"
        "- Nao escreva numeros de pagina.\n"
        "\n"
        "FORMATO OBRIGATORIO:\n"
        "Explicacao:\n"
        "<2-4 frases explicando o raciocinio correto>\n"
        "\n"
        "Possivel confusao:\n"
        "<1-2 frases sobre o que o estudante pode ter confundido>\n"
        "\n"
        "Onde estudar no livro:\n"
        "- <topico curto> (S1)\n"
        "\n"
        "Se nao houver fontes relevantes, diga isso explicitamente em 'Onde estudar no livro' e nao cite IDs."
    )


def build_user_prompt_for_question(
    ans: models.Answer,
    chunks: Sequence[models.Chunk],
) -> tuple[str, dict[str, models.Chunk]]:
    source_map: dict[str, models.Chunk] = {}
    source_lines: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        sid = f"S{idx}"
        source_map[sid] = chunk
        source_lines.append(f"{sid}: filename={chunk.filename}; page={chunk.page}; chunk_id={chunk.id}")

    sources_block = "\n".join(source_lines) if source_lines else "Sem fontes relevantes."

    correct_opt = next((o for o in ans.question.options if o.is_correct), None)
    correct_txt = f"{correct_opt.letter} - {correct_opt.text}" if correct_opt else "Desconhecida"
    selected_txt = f"{ans.option.letter} - {ans.option.text}"

    prompt = (
        f"Q{ans.question_id}: {ans.question.statement}\n"
        f"Resposta escolhida: {selected_txt}\n"
        f"Resposta correta: {correct_txt}\n"
        "\n"
        "Fontes (use apenas os IDs; nao inclua numeros de pagina):\n"
        f"{sources_block}\n"
    )
    return prompt, source_map


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
        sanitized.append(
            StudyItem(
                filename=item.filename,
                pages=pages,
                chapter=chapter,
            )
        )
    return sanitized


def _sanitize_per_question_feedback(pq: PerQuestionFeedback) -> PerQuestionFeedback:
    explanation = _truncate_chars(pq.explanation or "", EXPLANATION_MAX_CHARS)
    study = _sanitize_study_items(pq.study)
    return PerQuestionFeedback(
        question_id=pq.question_id,
        is_correct=pq.is_correct,
        explanation=explanation,
        study=study,
    )


def _build_study_groups(chunks: Sequence[models.Chunk]) -> list[StudyItem]:
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
    study = _build_study_groups(chunks[:4]) if chunks else []
    return PerQuestionFeedback(
        question_id=ans.question_id,
        is_correct=ans.is_correct,
        explanation=explanation,
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
) -> Mapping[int, Sequence[models.Chunk]]:
    per_q: dict[int, list[models.Chunk]] = {}
    for ans in attempt.answers:
        if ans.is_correct:
            continue
        q = _retrieval_query_for_answer(ans)
        per_q[ans.question_id] = list(retrieve_chunks(db, query=q, top_k=top_k))
    return per_q


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


def _generate_feedback_with_llm(
    llm,
    attempt: models.Attempt,
    per_q_chunks: Mapping[int, Sequence[models.Chunk]],
) -> FeedbackResponse:
    system_prompt = build_system_prompt_per_question()
    per_question: list[PerQuestionFeedback] = []

    for ans in attempt.answers:
        if ans.is_correct:
            continue

        chunks = per_q_chunks.get(ans.question_id, [])
        user_prompt, source_map = build_user_prompt_for_question(ans, chunks)
        fallback = False
        t1 = time.perf_counter()

        try:
            text = invoke_llm_for_question(llm, system_prompt, user_prompt)
            logger.info("LLM raw (truncated): %r", _truncate_text(text))
            ids = extract_source_ids(text, set(source_map.keys()))
            cited_chunks = map_source_ids_to_chunks(ids, source_map)
            study_chunks = cited_chunks if cited_chunks else chunks
            explanation = _strip_where_to_study(text)
            study = _build_study_groups(study_chunks)
            pq = PerQuestionFeedback(
                question_id=ans.question_id,
                is_correct=False,
                explanation=explanation,
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
    per_q_chunks = _retrieve_per_question(db, attempt, top_k=4)
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
        return _generate_feedback_with_llm(llm, attempt, per_q_chunks)
    except Exception:  # noqa: BLE001
        logger.exception("Feedback generation failed, falling back to default")
        return _default_feedback_from_per_q(attempt, per_q_chunks)
