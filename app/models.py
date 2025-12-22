from __future__ import annotations

import datetime as dt
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.db.base import Base


class EmbeddingType(TypeDecorator):
    """Vector column usable in Postgres while remaining test-friendly for SQLite."""

    impl = sa.types.LargeBinary
    cache_ok = True
    dimensions: int = 768

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON)


UserRole = Enum("student", "admin", name="user_role")
DocumentStatus = Enum("pending", "processing", "ready", "failed", name="document_status")
ChunkType = Enum("theory", "exercise", "unknown", name="chunk_type")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(UserRole, nullable=False, default="student")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    attempts: Mapped[List["Attempt"]] = relationship(back_populates="student", cascade="all, delete-orphan")


class Questionnaire(Base):
    __tablename__ = "questionnaires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    questions: Mapped[List["Question"]] = relationship(back_populates="questionnaire", cascade="all, delete-orphan")
    attempts: Mapped[List["Attempt"]] = relationship(back_populates="questionnaire")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    questionnaire: Mapped["Questionnaire"] = relationship(back_populates="questions")
    options: Mapped[List["Option"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    answers: Mapped[List["Answer"]] = relationship(back_populates="question")


class Option(Base):
    __tablename__ = "options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    letter: Mapped[str] = mapped_column(String(10), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    question: Mapped["Question"] = relationship(back_populates="options")

    __table_args__ = (UniqueConstraint("question_id", "letter", name="uq_option_letter"),)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    submitted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    score: Mapped[Optional[float]] = mapped_column(Float)
    total: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    questionnaire: Mapped["Questionnaire"] = relationship(back_populates="attempts")
    student: Mapped[Optional["User"]] = relationship(back_populates="attempts")
    answers: Mapped[List["Answer"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    selected_option_id: Mapped[int] = mapped_column(ForeignKey("options.id", ondelete="CASCADE"), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    attempt: Mapped["Attempt"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship(back_populates="answers")
    option: Mapped["Option"] = relationship()

    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_attempt_question"),)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(DocumentStatus, default="pending", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chunks: Mapped[List["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(EmbeddingType(), nullable=True)
    chunk_type: Mapped[str] = mapped_column(ChunkType, default="unknown", nullable=False)
    chapter_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    section_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_index"),
    )
