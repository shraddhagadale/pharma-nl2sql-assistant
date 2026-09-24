from fastapi.testclient import TestClient

from app.agent.models import AnalyticsPlan, AnswerSummary
from app.main import create_app


class FakePlanningModel:
    def __init__(self) -> None:
        self.plan_calls = 0

    async def plan(self, context):
        self.plan_calls += 1
        return AnalyticsPlan(
            metric_id="paid_demand",
            time_window_id="r3m",
            comparison_time_window_ids=[],
            dimension_ids=[],
            filters=["ZENOVAX only"],
            assumptions=["Paid demand uses distributor branded volume."],
            sql="""
                SELECT SUM(s.pack_units) AS pack_units
                FROM sales AS s
                WHERE s.data_source = 'distributor'
                  AND s.brand_flag = 1
                  AND s.mo_offset IN (0, 1, 2)
                  AND s.drug_name = :drug_name
            """,
            parameters=[{"name": "drug_name", "value": "ZENOVAX"}],
        )

    async def repair(self, context, prior_plan, issues):
        raise AssertionError(f"valid test SQL should not need repair: {issues}")

    async def summarize(self, context, plan, result):
        value = result.rows[0]["pack_units"] if result.rows else "0"
        return AnswerSummary(answer=f"ZENOVAX paid demand is {value} pack units.", notes=[])


def login(client: TestClient, user_id: str) -> None:
    response = client.post("/api/v1/demo/session", json={"user_id": user_id})
    assert response.status_code == 200


def test_chat_requires_session(client):
    response = client.post("/api/v1/chat", json={"question": "Show paid demand"})
    assert response.status_code == 401


def test_chat_reports_missing_model_configuration(client):
    login(client, "U001")
    response = client.post(
        "/api/v1/chat",
        json={"question": "Show paid demand for the last 3 months"},
    )
    assert response.status_code == 503
    assert "model is not configured" in response.json()["detail"]


def test_chat_executes_validated_parameterized_sql_with_rls(settings):
    model = FakePlanningModel()
    with TestClient(create_app(settings, model)) as client:
        login(client, "U009")
        response = client.post(
            "/api/v1/chat",
            json={
                "question": "Show ZENOVAX paid demand for the last 3 months",
                "include_sql": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["columns"] == ["pack_units"]
    assert body["rows"]
    assert body["sql"].endswith("LIMIT 100")
    assert "%(drug_name)s" in body["sql"]
    assert "New York Metro" in body["assumptions"][-1]
    assert model.plan_calls == 1


def test_chat_denies_ram_pricing_without_calling_model(settings):
    model = FakePlanningModel()
    with TestClient(create_app(settings, model)) as client:
        login(client, "U009")
        response = client.post(
            "/api/v1/chat",
            json={"question": "Show pricing for last month"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "denied"
    assert body["rows"] == []
    assert body["sql"] is None
    assert model.plan_calls == 0
