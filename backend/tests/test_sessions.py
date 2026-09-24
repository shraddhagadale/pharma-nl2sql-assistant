def test_demo_session_comes_from_database(client):
    users = client.get("/api/v1/demo/users")
    assert users.status_code == 200
    assert len(users.json()) == 23

    login = client.post("/api/v1/demo/session", json={"user_id": "U009"})
    assert login.status_code == 200
    assert login.json()["role"] == "ram"
    assert login.json()["territory_name"] == "New York Metro"
    assert login.json()["can_view_wac"] is False

    session = client.get("/api/v1/demo/session")
    assert session.status_code == 200
    assert session.json()["user_id"] == "U009"

    logout = client.delete("/api/v1/demo/session")
    assert logout.status_code == 204
    assert client.get("/api/v1/demo/session").status_code == 401


def test_login_rejects_unknown_user_and_client_supplied_role(client):
    unknown = client.post("/api/v1/demo/session", json={"user_id": "UNKNOWN"})
    assert unknown.status_code == 404

    injected_role = client.post(
        "/api/v1/demo/session",
        json={"user_id": "U009", "role": "exec"},
    )
    assert injected_role.status_code == 422
