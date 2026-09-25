import pytest

from app.agent.models import AnalyticsPlan, AnswerSummary, QueryResult
from app.agent.provider import UnavailablePlanningModel
from app.agent.workflow import AgentUnavailableError, AgentWorkflow
from app.audit import AuditLogger
from app.models import ChatStatus, ConversationRole, ConversationTurn, UserContext, UserRole
from app.sql.validator import SqlValidator

VALID_SQL = """
    SELECT SUM(s.pack_units) AS paid_demand
    FROM sales AS s
    WHERE s.data_source = 'distributor'
      AND s.brand_flag = 1
      AND s.mo_offset IN (0, 1, 2)
"""


def user(role: UserRole) -> UserContext:
    return UserContext(
        user_id={UserRole.EXEC: "U001", UserRole.DIRECTOR: "U003", UserRole.RAM: "U009"}[role],
        email=f"{role.value}@example.test",
        full_name=role.value.title(),
        role=role,
        territory_name="New York Metro" if role is UserRole.RAM else None,
        region_name="Northeast" if role is not UserRole.EXEC else None,
        can_view_wac=role is UserRole.EXEC,
    )


def plan(sql: str = VALID_SQL) -> AnalyticsPlan:
    return AnalyticsPlan(
        metric_id="paid_demand",
        time_window_id="r3m",
        comparison_time_window_ids=[],
        dimension_ids=[],
        filters=["Distributor branded volume"],
        assumptions=["Paid demand excludes free drug."],
        sql=sql,
        parameters=[],
    )


class FakeModel:
    def __init__(
        self,
        *,
        initial: AnalyticsPlan,
        repaired: AnalyticsPlan | None = None,
        fail_summary: bool = False,
    ) -> None:
        self.initial = initial
        self.repaired = repaired or initial
        self.fail_summary = fail_summary
        self.plan_calls = 0
        self.repair_calls = 0
        self.last_context = None

    async def plan(self, context):
        self.plan_calls += 1
        self.last_context = context
        return self.initial

    async def repair(self, context, prior_plan, issues):
        self.repair_calls += 1
        return self.repaired

    async def summarize(self, context, current_plan, result):
        if self.fail_summary:
            from app.agent.provider import PlanningModelError

            raise PlanningModelError("summary failed")
        return AnswerSummary(answer="Paid demand is 42 units.", notes=[])


class StubExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, query, *, user):
        self.calls += 1
        return QueryResult(columns=["paid_demand"], rows=[{"paid_demand": "42"}])


def workflow(model, executor, *, max_repairs: int = 1) -> AgentWorkflow:
    return AgentWorkflow(
        model=model,
        validator=SqlValidator(max_rows=100),
        executor=executor,
        audit=AuditLogger(),
        max_repairs=max_repairs,
    )


@pytest.mark.asyncio
async def test_non_exec_revenue_is_denied_before_model_call() -> None:
    model = FakeModel(
        initial=AnalyticsPlan(
            decision="denied",
            response=(
                "Revenue in dollars is available only to executives. "
                "I can show paid demand instead."
            ),
        )
    )
    executor = StubExecutor()

    result = await workflow(model, executor).run(
        question="Show pricing last month",
        conversation=[],
        user=user(UserRole.RAM),
        include_sql=False,
        request_id="request-1",
    )

    assert result.status is ChatStatus.DENIED
    assert "only to executives" in result.answer
    assert "paid demand" in result.answer
    assert model.plan_calls == 1
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_invalid_sql_is_repaired_once_then_executed() -> None:
    model = FakeModel(initial=plan("SELECT * FROM sales"), repaired=plan())
    executor = StubExecutor()

    result = await workflow(model, executor).run(
        question="Show paid demand for the last 3 months",
        conversation=[],
        user=user(UserRole.RAM),
        include_sql=True,
        request_id="request-2",
    )

    assert result.status is ChatStatus.ANSWERED
    assert result.answer == "Paid demand is 42 units."
    assert result.rows == [{"paid_demand": "42"}]
    assert result.sql is not None and result.sql.endswith("LIMIT 100")
    assert model.repair_calls == 1
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_retry_exhaustion_fails_closed_without_execution() -> None:
    model = FakeModel(initial=plan("SELECT * FROM sales"))
    executor = StubExecutor()

    result = await workflow(model, executor).run(
        question="Show paid demand for the last 3 months",
        conversation=[],
        user=user(UserRole.EXEC),
        include_sql=True,
        request_id="request-3",
    )

    assert result.status is ChatStatus.REJECTED
    assert result.sql is None
    assert model.repair_calls == 1
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_summary_failure_returns_validated_table_fallback() -> None:
    model = FakeModel(initial=plan(), fail_summary=True)
    executor = StubExecutor()

    result = await workflow(model, executor).run(
        question="Show paid demand for the last 3 months",
        conversation=[],
        user=user(UserRole.EXEC),
        include_sql=False,
        request_id="request-4",
    )

    assert result.status is ChatStatus.ANSWERED
    assert result.answer == "I found the requested information and included it below."
    assert result.assumptions == [
        "Paid demand excludes free drug.",
        "Showing company-wide results.",
    ]


@pytest.mark.asyncio
async def test_missing_model_configuration_is_reported_as_unavailable() -> None:
    with pytest.raises(AgentUnavailableError):
        await workflow(UnavailablePlanningModel(), StubExecutor()).run(
            question="Show paid demand for the last 3 months",
            conversation=[],
            user=user(UserRole.EXEC),
            include_sql=False,
            request_id="request-5",
        )


@pytest.mark.asyncio
async def test_referential_follow_up_uses_bounded_prior_user_context() -> None:
    follow_up_plan = AnalyticsPlan(
        metric_id="paid_demand",
        time_window_id="last_month",
        comparison_time_window_ids=[],
        dimension_ids=[],
        filters=["Distributor branded volume"],
        assumptions=[],
        sql="""
            SELECT SUM(s.pack_units) AS paid_demand
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset = 1
        """,
        parameters=[],
    )
    model = FakeModel(initial=follow_up_plan)

    result = await workflow(model, StubExecutor()).run(
        question="What about last month?",
        conversation=[
            ConversationTurn(
                role=ConversationRole.USER,
                content="Show paid demand for the last 3 months.",
            ),
            ConversationTurn(
                role=ConversationRole.ASSISTANT,
                content="Paid demand was 42 units.",
            ),
        ],
        user=user(UserRole.RAM),
        include_sql=False,
        request_id="request-6",
    )

    assert result.status is ChatStatus.ANSWERED
    assert model.last_context.question == "What about last month?"
    assert model.last_context.conversation[0].content == ("Show paid demand for the last 3 months.")
