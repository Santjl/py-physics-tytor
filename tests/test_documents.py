import fitz

from app import models


def _login(client, email: str, password: str) -> str:
    resp = client.post(
        "/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def make_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_upload_pdf_processes_chunks(client, admin_user, db_session):
    token = _login(client, admin_user.email, "secret")
    pdf_bytes = make_pdf_bytes("Gravity on Earth is approximately 9.8 m/s^2.")

    resp = client.post(
        "/documents/upload",
        files={"file": ("gravity.pdf", pdf_bytes, "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    document_id = resp.json()["id"]
    assert resp.json()["status"] == "ready"

    status_resp = client.get(f"/documents/{document_id}", headers={"Authorization": f"Bearer {token}"})
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "ready"

    chunks = db_session.query(models.Chunk).filter_by(document_id=document_id).all()
    assert len(chunks) >= 1
    assert chunks[0].filename == "gravity.pdf"
