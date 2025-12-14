from __future__ import annotations

import json
import logging
from typing import List, Sequence

from langchain_community.chat_models import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

from app import models
from app.core.config import get_settings
from app.rag.retrieval import retrieve_chunks
from app.schemas import FeedbackResponse, Citation, StudyRecommendation, PerQuestionFeedback, SummaryFeedback

logger = logging.getLogger(__name__)


def _format_sources(chunks: Sequence[models.Chunk]) -> str:
    lines = []
    for chunk in chunks:
        lines.append(f"[SOURCE: {chunk.filename} p.{chunk.page} id={chunk.id}]\n{chunk.text}")
    return "\n\n".join(lines)


def _build_system_prompt() -> str:
    return (
        "You are an assistant that produces ONLY valid JSON for quiz feedback.\n"
        "You must cite sources strictly from provided chunks.\n"
        "Do not invent citations. Every study_recommendations entry must have at least one citation unless none are provided.\n"
        "Output JSON schema:\n"
        "{\n"
        '  "attempt_id": <int>,\n'
        '  "summary": {"score": <number>, "total": <int>, "strengths": [], "weaknesses": []},\n'
        '  "per_question": [\n'
        '    {"question_id": <int>, "is_correct": true/false, "explanation": "", "study_recommendations": [\n'
        '      {"title": "", "why": "", "citations": [ {"filename": "", "page": <int>, "snippet": ""} ]}\n'
        "    ]}\n"
        "  ],\n"
        '  "global_references": [ {"filename": "", "page": <int>, "snippet": ""} ]\n'
        "}"
    )


def _build_user_prompt(attempt: models.Attempt, chunks: Sequence[models.Chunk]) -> str:
    qa = []
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


def _default_feedback(attempt: models.Attempt, chunks: Sequence[models.Chunk]) -> FeedbackResponse:
    citation_items: List[Citation] = []
    if chunks:
        c = chunks[0]
        snippet = c.text[:240]
        citation_items.append(Citation(filename=c.filename, page=c.page, snippet=snippet))
    per_question = [
        PerQuestionFeedback(
            question_id=ans.question_id,
            is_correct=ans.is_correct,
            explanation="Review the concept and compare with provided sources." if citation_items else "Review the concept.",
            study_recommendations=[
                StudyRecommendation(
                    title="Review related section",
                    why="Based on your answer, revisit this topic.",
                    citations=citation_items,
                )
            ]
            if citation_items
            else [],
        )
        for ans in attempt.answers
    ]
    summary = SummaryFeedback(
        score=attempt.score or 0.0,
        total=attempt.total or 0,
        strengths=["Answered correctly"] if (attempt.score or 0) > 0 else [],
        weaknesses=["Missed questions"] if (attempt.score or 0) < (attempt.total or 0) else [],
    )
    return FeedbackResponse(
        attempt_id=attempt.id,
        summary=summary,
        per_question=per_question,
        global_references=citation_items,
    )


def generate_feedback(db, attempt: models.Attempt, query: str = "physics study tips") -> FeedbackResponse:
    settings = get_settings()
    chunks = retrieve_chunks(db, query=query, top_k=8)

    if settings.app_env.lower() == "test":
        return _default_feedback(attempt, chunks)

    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_chat_model,
        temperature=0.2,
    )
    messages = [
        SystemMessage(content=_build_system_prompt()),
        HumanMessage(content=_build_user_prompt(attempt, chunks)),
    ]
    try:
        result = llm.invoke(messages)
        data = json.loads(result.content)
        return FeedbackResponse.model_validate(data)
    except Exception:  # noqa: BLE001
        logger.exception("Feedback generation failed, falling back to default")
        return _default_feedback(attempt, chunks)
