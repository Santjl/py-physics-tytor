from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.schemas import AttemptAnswerInput


def score_attempt(
    db: Session, questionnaire_id: int, answers: Iterable[AttemptAnswerInput], student_id: Optional[int] = None
) -> models.Attempt:
    questionnaire = db.get(models.Questionnaire, questionnaire_id)
    if not questionnaire:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")

    answer_items = list(answers)
    if not answer_items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one answer is required")

    question_ids = {q.id for q in questionnaire.questions}
    requested_question_ids = {a.question_id for a in answer_items}
    unknown_questions = requested_question_ids - question_ids
    if unknown_questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Questions {sorted(unknown_questions)} do not belong to questionnaire",
        )

    options_map = {
        o.id: o
        for o in db.scalars(select(models.Option).join(models.Question).where(models.Question.questionnaire_id == questionnaire_id))
    }

    attempt = models.Attempt(
        questionnaire_id=questionnaire_id,
        student_id=student_id,
        submitted_at=dt.datetime.utcnow(),
    )
    db.add(attempt)
    db.flush()

    correct_count = 0
    for answer_input in answer_items:
        option = options_map.get(answer_input.selected_option_id)
        if not option:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid option selected")
        if option.question_id != answer_input.question_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Option {option.id} does not belong to question {answer_input.question_id}",
            )
        is_correct = option.is_correct
        if is_correct:
            correct_count += 1

        db.add(
            models.Answer(
                attempt_id=attempt.id,
                question_id=answer_input.question_id,
                selected_option_id=answer_input.selected_option_id,
                is_correct=is_correct,
            )
        )

    attempt.score = float(correct_count)
    attempt.total = len(answer_items)
    db.commit()
    db.refresh(attempt)
    return attempt
