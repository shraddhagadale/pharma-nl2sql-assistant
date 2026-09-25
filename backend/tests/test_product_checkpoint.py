from fastapi.testclient import TestClient

from app.agent.models import AnalyticsPlan, AnswerSummary
from app.main import create_app


class CheckpointPlanningModel:
    def __init__(self) -> None:
        self.plan_calls = 0

    async def plan(self, context):
        self.plan_calls += 1
        selection = context.selection
        metric_id = selection.metric_ids[0]

        if metric_id == "gross_revenue":
            return AnalyticsPlan(
                metric_id="gross_revenue",
                time_window_id="last_month",
                comparison_time_window_ids=[],
                dimension_ids=[],
                filters=[],
                assumptions=["Revenue uses distributor branded WAC."],
                sql="""
                    SELECT SUM(s.wac) AS gross_revenue
                    FROM sales AS s
                    WHERE s.data_source = 'distributor'
                      AND s.brand_flag = 1
                      AND s.mo_offset = 1
                """,
                parameters=[],
            )

        if selection.dimension_ids == ["account"]:
            return AnalyticsPlan(
                metric_id="paid_demand",
                time_window_id="last_quarter",
                comparison_time_window_ids=[],
                dimension_ids=["account"],
                filters=[],
                assumptions=["Accounts use the documented grandparent rollup."],
                sql="""
                    SELECT
                      COALESCE(o.grandparent_org_name, o.org_name) AS account,
                      SUM(s.pack_units) AS paid_demand
                    FROM sales AS s
                    JOIN organizations AS o ON o.org_id = s.org_id
                    WHERE s.data_source = 'distributor'
                      AND s.brand_flag = 1
                      AND s.mo_offset IN (1, 2, 3)
                    GROUP BY COALESCE(o.grandparent_org_name, o.org_name)
                    ORDER BY paid_demand DESC
                    LIMIT 10
                """,
                parameters=[],
            )

        if selection.comparison_time_window_ids:
            return AnalyticsPlan(
                metric_id="paid_demand",
                time_window_id="prior_r3m",
                comparison_time_window_ids=["r3m"],
                dimension_ids=[],
                filters=[],
                assumptions=["The two documented three-month windows are compared."],
                sql="""
                    SELECT
                      SUM(CASE WHEN s.mo_offset IN (0, 1, 2)
                        THEN s.pack_units ELSE 0 END) AS r3m_paid_demand,
                      SUM(CASE WHEN s.mo_offset IN (3, 4, 5)
                        THEN s.pack_units ELSE 0 END) AS prior_r3m_paid_demand
                    FROM sales AS s
                    WHERE s.data_source = 'distributor'
                      AND s.brand_flag = 1
                      AND s.mo_offset BETWEEN 0 AND 5
                """,
                parameters=[],
            )

        return AnalyticsPlan(
            metric_id="paid_demand",
            time_window_id="r3m",
            comparison_time_window_ids=[],
            dimension_ids=[],
            filters=[],
            assumptions=["Paid demand uses distributor branded volume."],
            sql="""
                SELECT SUM(s.pack_units) AS paid_demand
                FROM sales AS s
                WHERE s.data_source = 'distributor'
                  AND s.brand_flag = 1
                  AND s.mo_offset IN (0, 1, 2)
            """,
            parameters=[],
        )

    async def repair(self, context, prior_plan, issues):
        raise AssertionError(f"checkpoint plans must pass on their first attempt: {issues}")

    async def summarize(self, context, plan, result):
        return AnswerSummary(
            answer=f"Validated {plan.metric_id} result with {len(result.rows)} row(s).",
            notes=[],
        )


def login(client: TestClient, user_id: str) -> None:
    response = client.post("/api/v1/demo/session", json={"user_id": user_id})
    assert response.status_code == 200


def ask(client: TestClient, question: str, conversation=None) -> dict:
    response = client.post(
        "/api/v1/chat",
        json={
            "question": question,
            "conversation": conversation or [],
            "include_sql": True,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_paid_demand_is_scoped_differently_for_ram_director_and_exec(settings) -> None:
    values: dict[str, float] = {}
    with TestClient(create_app(settings, CheckpointPlanningModel())) as client:
        for user_id in ("U009", "U003", "U001"):
            login(client, user_id)
            result = ask(client, "Show paid demand for the last 3 months")
            assert result["status"] == "answered"
            assert result["sql"].endswith("LIMIT 100")
            values[user_id] = float(result["rows"][0]["paid_demand"])

    assert 0 < values["U009"] < values["U003"] < values["U001"]


def test_pricing_denial_and_executive_revenue(settings) -> None:
    model = CheckpointPlanningModel()
    with TestClient(create_app(settings, model)) as client:
        login(client, "U009")
        denied = ask(client, "Show pricing last month")
        assert denied["status"] == "denied"
        assert denied["sql"] is None
        assert model.plan_calls == 0

        login(client, "U001")
        revenue = ask(client, "Show gross revenue last month")
        assert revenue["status"] == "answered"
        assert float(revenue["rows"][0]["gross_revenue"]) > 0
        assert "wac" in revenue["sql"].casefold()


def test_ranked_accounts_and_multi_turn_period_comparison(settings) -> None:
    with TestClient(create_app(settings, CheckpointPlanningModel())) as client:
        login(client, "U003")
        ranked = ask(client, "Rank the top accounts by pack units last quarter")
        assert ranked["status"] == "answered"
        assert ranked["columns"] == ["account", "paid_demand"]
        assert 1 <= len(ranked["rows"]) <= 10

        comparison = ask(
            client,
            "What about R3M versus prior R3M?",
            conversation=[
                {"role": "user", "content": "Show paid demand for the last 3 months"},
                {"role": "assistant", "content": "Paid demand was returned."},
            ],
        )
        assert comparison["status"] == "answered"
        assert comparison["columns"] == ["r3m_paid_demand", "prior_r3m_paid_demand"]
