from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.deps import get_db
from app.schemas import (
    AttemptCreate,
    AttemptResult,
    QuestionCreate,
    QuestionRead,
    QuestionnaireCreate,
    QuestionnaireDetail,
    QuestionnaireRead,
    AttemptAnswerResult,
)
from app.services.attempts import score_attempt
from app.api.routes.auth import require_admin, require_student

router = APIRouter(prefix="/questionnaires", tags=["questionnaires"])


@router.post("/", response_model=QuestionnaireRead, status_code=status.HTTP_201_CREATED)
def create_questionnaire(
    payload: QuestionnaireCreate, db: Session = Depends(get_db), _: models.User = Depends(require_admin)
):
    questionnaire = models.Questionnaire(title=payload.title, description=payload.description)
    db.add(questionnaire)
    db.commit()
    db.refresh(questionnaire)
    return questionnaire


@router.get("/", response_model=List[QuestionnaireRead])
def list_questionnaires(db: Session = Depends(get_db)):
    return db.scalars(select(models.Questionnaire).order_by(models.Questionnaire.id)).all()


@router.get("/{questionnaire_id}", response_model=QuestionnaireDetail)
def get_questionnaire(questionnaire_id: int, db: Session = Depends(get_db)):
    questionnaire = db.get(models.Questionnaire, questionnaire_id)
    if not questionnaire:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")
    return questionnaire


@router.post("/{questionnaire_id}/questions", response_model=QuestionRead, status_code=status.HTTP_201_CREATED)
def add_question(
    questionnaire_id: int, payload: QuestionCreate, db: Session = Depends(get_db), _: models.User = Depends(require_admin)
):
    questionnaire = db.get(models.Questionnaire, questionnaire_id)
    if not questionnaire:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")
    if not payload.options:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A question requires at least one option")

    question = models.Question(questionnaire_id=questionnaire_id, statement=payload.statement)
    db.add(question)
    db.flush()

    for option in payload.options:
        db.add(
            models.Option(
                question_id=question.id,
                letter=option.letter,
                text=option.text,
                is_correct=option.is_correct,
            )
        )

    db.commit()
    db.refresh(question)
    return question


@router.get("/{questionnaire_id}/questions", response_model=List[QuestionRead])
def list_questions(questionnaire_id: int, db: Session = Depends(get_db)):
    questionnaire = db.get(models.Questionnaire, questionnaire_id)
    if not questionnaire:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")

    questions = db.scalars(
        select(models.Question).where(models.Question.questionnaire_id == questionnaire_id).order_by(models.Question.id)
    ).all()
    return questions


@router.post("/{questionnaire_id}/attempts", response_model=AttemptResult, status_code=status.HTTP_201_CREATED)
def submit_attempt(
    questionnaire_id: int,
    payload: AttemptCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student),
):
    attempt = score_attempt(db, questionnaire_id=questionnaire_id, answers=payload.answers, student_id=current_user.id)
    answers = [
        AttemptAnswerResult(
            question_id=answer.question_id, selected_option_id=answer.selected_option_id, is_correct=answer.is_correct
        )
        for answer in attempt.answers
    ]
    return AttemptResult(attempt_id=attempt.id, score=attempt.score or 0.0, total=attempt.total or 0, answers=answers)
