from app.schemas import AttemptAnswerInput
from app.services.attempts import score_attempt
from app import models


def test_score_attempt_counts_correct_answers(db_session):
    questionnaire = models.Questionnaire(title="Eval", description=None)
    db_session.add(questionnaire)
    db_session.flush()

    q = models.Question(questionnaire_id=questionnaire.id, statement="Unit?")
    db_session.add(q)
    db_session.flush()

    opt_correct = models.Option(question_id=q.id, letter="A", text="m/s", is_correct=True)
    opt_wrong = models.Option(question_id=q.id, letter="B", text="kg", is_correct=False)
    db_session.add_all([opt_correct, opt_wrong])
    db_session.commit()

    attempt = score_attempt(
        db_session,
        questionnaire_id=questionnaire.id,
        answers=[AttemptAnswerInput(question_id=q.id, selected_option_id=opt_wrong.id)],
        student_id=None,
    )
    assert attempt.score == 0
    assert attempt.total == 1
    assert attempt.answers[0].is_correct is False
