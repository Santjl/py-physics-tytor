from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine
from app.db.base import Base
from app import models


def seed(session: Session) -> None:
    if session.query(models.Questionnaire).count() > 0:
        return

    questionnaire = models.Questionnaire(title="Kinematics Basics", description="Displacement, velocity, and acceleration")
    session.add(questionnaire)
    session.flush()

    question = models.Question(questionnaire_id=questionnaire.id, statement="What is constant in uniform motion?")
    session.add(question)
    session.flush()

    session.add_all(
        [
            models.Option(question_id=question.id, letter="A", text="Acceleration", is_correct=False),
            models.Option(question_id=question.id, letter="B", text="Velocity", is_correct=True),
            models.Option(question_id=question.id, letter="C", text="Displacement", is_correct=False),
        ]
    )

    session.commit()


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed(session)


if __name__ == "__main__":
    main()
