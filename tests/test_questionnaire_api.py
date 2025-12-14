from app import models


def _login(client, email: str, password: str) -> str:
    resp = client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_create_questionnaire_and_questions(client, admin_user):
    token = _login(client, admin_user.email, "secret")
    create_resp = client.post(
        "/questionnaires",
        json={"title": "Dynamics", "description": "Newton's laws basics"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201, create_resp.text
    questionnaire_id = create_resp.json()["id"]

    question_payload = {
        "statement": "Which law explains action and reaction?",
        "options": [
            {"letter": "A", "text": "First law", "is_correct": False},
            {"letter": "B", "text": "Second law", "is_correct": False},
            {"letter": "C", "text": "Third law", "is_correct": True},
        ],
    }
    question_resp = client.post(
        f"/questionnaires/{questionnaire_id}/questions",
        json=question_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert question_resp.status_code == 201, question_resp.text

    questions_resp = client.get(f"/questionnaires/{questionnaire_id}/questions")
    assert questions_resp.status_code == 200
    questions = questions_resp.json()
    assert len(questions) == 1
    assert questions[0]["statement"] == question_payload["statement"]
    assert any(option["is_correct"] for option in questions[0]["options"])


def test_submit_attempt_scores_correctly(client, admin_user, student_user):
    admin_token = _login(client, admin_user.email, "secret")
    student_token = _login(client, student_user.email, "secret")

    create_resp = client.post(
        "/questionnaires",
        json={"title": "Energy", "description": "Work-energy"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    questionnaire_id = create_resp.json()["id"]

    question_payload = {
        "statement": "SI unit of energy?",
        "options": [
            {"letter": "A", "text": "Newton", "is_correct": False},
            {"letter": "B", "text": "Joule", "is_correct": True},
        ],
    }
    question_resp = client.post(
        f"/questionnaires/{questionnaire_id}/questions",
        json=question_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert question_resp.status_code == 201
    question_data = question_resp.json()
    correct_option_id = next(o["id"] for o in question_data["options"] if o["is_correct"])

    attempt_resp = client.post(
        f"/questionnaires/{questionnaire_id}/attempts",
        json={"answers": [{"question_id": question_data["id"], "selected_option_id": correct_option_id}]},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert attempt_resp.status_code == 201, attempt_resp.text
    attempt_data = attempt_resp.json()
    assert attempt_data["score"] == 1
    assert attempt_data["total"] == 1
    assert attempt_data["answers"][0]["is_correct"] is True
