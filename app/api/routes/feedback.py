from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.api.deps import get_db
from app.api.routes.auth import require_student
from app.rag.feedback import generate_feedback
from app.schemas import FeedbackResponse

router = APIRouter(prefix="/attempts", tags=["feedback"])


@router.post("/{attempt_id}/feedback", response_model=FeedbackResponse, status_code=status.HTTP_200_OK)
def get_feedback(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student),
):
    attempt = db.get(models.Attempt, attempt_id)
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found")
    if attempt.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your attempt")

    # Ensure answers and options are loaded
    db.execute(select(models.Answer).where(models.Answer.attempt_id == attempt_id)).all()
    return generate_feedback(db, attempt)
