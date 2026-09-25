import pytest

from app.agent.models import AnalyticsPlan, AnswerSummary, QueryResult
from app.agent.workflow import AgentWorkflow
from app.audit import AuditLogger
from app.models import ChatStatus, UserContext, UserRole
from app.sql.validator import SqlValidator

VALID_SQL = """
    SELECT SUM(s.pack_units) AS paid_demand
    FROM sales AS s
    WHERE s.data_source = 'distributor'
      AND s.brand_flag = 1
      AND s.mo_offset IN (0, 1, 2)
"""


def scoped_user() -> UserContext:
    return UserContext(
        user_id="test-user",
        email="test@example.test",
        full_name="Test User",
        role=UserRole.RAM,
        territory_name="Central Plains",
        region_name="Central",
        can_view_wac=False,
    )


def plan(*, geography=None, assumptions=None) -> AnalyticsPlan:
    return AnalyticsPlan(
        metric_id="paid_demand",
        time_window_id="r3m",
        comparison_time_window_ids=[],
        dimension_ids=[],
        filters=["Branded distributor volume"],
        assumptions=assumptions or [],
        geography=geography,
        sql=VALID_SQL,
        parameters=[],
    )


class QualityModel:
    def __init__(self, analytics_plan: AnalyticsPlan, answer: str = "Paid demand was 42 units."):
        self.analytics_plan = analytics_plan
        self.answer = answer
        self.summary_calls = 0

    async def plan(self, context):
        return self.analytics_plan

    async def repair(self, context, prior_plan, issues):
        raise AssertionError(f"quality-test plan unexpectedly needed repair: {issues}")

    async def summarize(self, context, current_plan, result):
        self.summary_calls += 1
        return AnswerSummary(answer=self.answer, notes=[])


class QualityExecutor:
    def __init__(self, *, result=None, error=None):
        self.result = result or QueryResult(
            columns=["paid_demand"],
            rows=[{"paid_demand": "42"}],
        )
        self.error = error
        self.calls = 0

    async def execute(self, query, *, user):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class QualityGeography:
    def __init__(self, within_scope: bool | None) -> None:
        self.within_scope = within_scope
        self.calls = 0

    async def is_within_scope(self, reference, *, user):
        self.calls += 1
        return self.within_scope


def workflow(model, executor, *, geography=None) -> AgentWorkflow:
    return AgentWorkflow(
        model=model,
        validator=SqlValidator(max_rows=100),
        executor=executor,
        geography=geography,
        audit=AuditLogger(),
        max_repairs=1,
    )


async def run(model, executor, *, geography=None):
    return await workflow(model, executor, geography=geography).run(
        question="Show paid demand for the requested location",
        conversation=[],
        user=scoped_user(),
        include_sql=False,
        request_id="quality-request",
    )


@pytest.mark.asyncio
async def test_city_without_state_requests_clarification_before_execution() -> None:
    model = QualityModel(plan(geography={"kind": "city", "name": "Springfield"}))
    executor = QualityExecutor()

    response = await run(model, executor)

    assert response.status is ChatStatus.CLARIFICATION
    assert response.answer == "Which state do you mean for Springfield?"
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_out_of_scope_territory_offers_the_users_assigned_scope() -> None:
    model = QualityModel(plan(geography={"kind": "territory", "name": "Coastal North"}))
    executor = QualityExecutor()

    response = await run(model, executor)

    assert response.status is ChatStatus.DENIED
    assert response.answer == (
        "That location is outside your assigned territory. I can help with Central Plains instead."
    )
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_confirmed_city_outside_scope_is_denied_before_analytics_execution() -> None:
    model = QualityModel(plan(geography={"kind": "city", "name": "Riverton", "state": "Westland"}))
    executor = QualityExecutor()
    geography = QualityGeography(within_scope=False)

    response = await run(model, executor, geography=geography)

    assert response.status is ChatStatus.DENIED
    assert "outside your assigned territory" in response.answer
    assert geography.calls == 1
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_null_aggregate_becomes_business_friendly_no_data() -> None:
    model = QualityModel(plan())
    executor = QualityExecutor(
        result=QueryResult(columns=["paid_demand"], rows=[{"paid_demand": None}])
    )

    response = await run(model, executor)

    assert response.status is ChatStatus.NO_DATA
    assert response.rows == []
    assert "null" not in response.answer.casefold()
    assert "row" not in response.answer.casefold()
    assert model.summary_calls == 0


@pytest.mark.asyncio
async def test_timeout_and_other_failures_have_distinct_business_messages() -> None:
    timeout = await run(
        QualityModel(plan()),
        QualityExecutor(error=TimeoutError("statement timeout")),
    )
    failure = await run(
        QualityModel(plan()),
        QualityExecutor(error=RuntimeError("connection lost")),
    )

    assert timeout.status is ChatStatus.ERROR
    assert "took too long" in timeout.answer
    assert failure.status is ChatStatus.ERROR
    assert failure.answer == "I couldn't complete that analysis right now. Please try again."


@pytest.mark.asyncio
async def test_technical_model_language_is_replaced_and_not_exposed_in_notes() -> None:
    model = QualityModel(
        plan(
            assumptions=[
                "The SQL query uses a database offset.",
                "Paid demand excludes free drug.",
            ]
        ),
        answer="The validated query returned one database row.",
    )

    response = await run(model, QualityExecutor())

    assert response.status is ChatStatus.ANSWERED
    assert response.answer == "I found the requested information and included it below."
    assert response.assumptions == [
        "Paid demand excludes free drug.",
        "Showing results for your assigned territory: Central Plains.",
    ]
