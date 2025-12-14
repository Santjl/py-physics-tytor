from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# Questionnaire and question schemas
class OptionCreate(BaseModel):
    letter: str
    text: str
    is_correct: bool = False


class OptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    letter: str
    text: str
    is_correct: bool


class QuestionCreate(BaseModel):
    statement: str
    options: List[OptionCreate]


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    statement: str
    options: List[OptionRead]


class QuestionnaireCreate(BaseModel):
    title: str
    description: Optional[str] = None


class QuestionnaireRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str]


class QuestionnaireDetail(QuestionnaireRead):
    questions: List[QuestionRead] = []


# Attempts
class AttemptAnswerInput(BaseModel):
    question_id: int
    selected_option_id: int


class AttemptCreate(BaseModel):
    answers: List[AttemptAnswerInput] = Field(default_factory=list)


class AttemptAnswerResult(BaseModel):
    question_id: int
    selected_option_id: int
    is_correct: bool


class AttemptResult(BaseModel):
    attempt_id: int
    score: float
    total: int
    answers: List[AttemptAnswerResult]


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    status: str
    created_at: Optional[str] = None
