from app import models


def _login(client, email: str, password: str) -> str:
    resp = client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_feedback_returns_citations(client, admin_user, student_user, db_session):
    admin_token = _login(client, admin_user.email, "secret")
    student_token = _login(client, student_user.email, "secret")

    # Create questionnaire and question
    q_resp = client.post(
        "/questionnaires",
        json={"title": "Kinematics", "description": "Basics"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    qid = q_resp.json()["id"]
    question_resp = client.post(
        f"/questionnaires/{qid}/questions",
        json={
            "statement": "Speed units?",
            "options": [
                {"letter": "A", "text": "m/s", "is_correct": True},
                {"letter": "B", "text": "kg", "is_correct": False},
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    question = question_resp.json()
    incorrect_option_id = next(o["id"] for o in question["options"] if not o["is_correct"])

    # Submit attempt
    attempt_resp = client.post(
        f"/questionnaires/{qid}/attempts",
        json={"answers": [{"question_id": question["id"], "selected_option_id": incorrect_option_id}]},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    attempt_id = attempt_resp.json()["attempt_id"]

    # Seed a chunk for retrieval
    doc = models.Document(filename="study.pdf", status="ready")
    db_session.add(doc)
    db_session.flush()
    chunk = models.Chunk(
        document_id=doc.id,
        filename=doc.filename,
        page=1,
        chunk_index=0,
        text="Speed is measured in meters per second (m/s).",
        embedding=[0.1] * 768,
    )
    db_session.add(chunk)
    db_session.commit()

    feedback_resp = client.post(
        f"/attempts/{attempt_id}/feedback",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert feedback_resp.status_code == 200, feedback_resp.text
    data = feedback_resp.json()
    assert data["attempt_id"] == attempt_id
    assert data["per_question"][0]["study"]
    study_item = data["per_question"][0]["study"][0]
    assert study_item["filename"] == "study.pdf"
    assert 1 in study_item["pages"]
