def login(client, user_id: str) -> None:
    response = client.post("/api/v1/demo/session", json={"user_id": user_id})
    assert response.status_code == 200


def test_analytics_requires_session(client):
    response = client.get("/api/v1/analytics/overview")
    assert response.status_code == 401


def test_overview_uses_role_scoped_pool_and_hides_wac(client):
    login(client, "U009")
    ram = client.get("/api/v1/analytics/overview", params={"months": 3})
    assert ram.status_code == 200
    ram_body = ram.json()
    assert ram_body["user"]["territory_name"] == "New York Metro"
    assert ram_body["revenue"] is None
    assert ram_body["revenue_visible"] is False

    client.delete("/api/v1/demo/session")
    login(client, "U001")
    executive = client.get("/api/v1/analytics/overview", params={"months": 3})
    assert executive.status_code == 200
    executive_body = executive.json()
    assert executive_body["revenue_visible"] is True
    assert executive_body["revenue"] is not None
    assert executive_body["organization_count"] >= ram_body["organization_count"]


def test_overview_validates_period_bound(client):
    login(client, "U001")
    assert client.get("/api/v1/analytics/overview", params={"months": 0}).status_code == 422
    assert client.get("/api/v1/analytics/overview", params={"months": 13}).status_code == 422
