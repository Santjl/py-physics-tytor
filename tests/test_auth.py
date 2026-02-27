def test_register_and_login_flow(client):
    register_resp = client.post(
        "/auth/register",
        json={"email": "newstudent@example.com", "password": "mypass", "role": "student"},
    )
    assert register_resp.status_code == 201, register_resp.text
    assert register_resp.json()["role"] == "student"

    login_resp = client.post(
        "/auth/login",
        data={"username": "newstudent@example.com", "password": "mypass"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200, login_resp.text
    assert "access_token" in login_resp.json()
