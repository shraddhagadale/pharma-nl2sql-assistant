import asyncio
from time import perf_counter

from app.agent.models import (
    AnalyticsPlan,
    AnswerSummary,
    PlanDecision,
    PlanningContext,
    QueryResult,
)
from app.agent.outcomes import ConversationOutcomeClassifier, plain_business_text
from app.agent.provider import PlanningModel, PlanningModelError
from app.audit import AuditEvent, AuditLogger
from app.db.geography import GeographyScopeRepository
from app.models import (
    ChatResponse,
    ChatStatus,
    ConversationTurn,
    UserContext,
)
from app.sql.executor import QueryExecutor, UnknownProductError
from app.sql.schema import role_safe_schema
from app.sql.validator import (
    MissingMarketContextError,
    SqlValidationError,
    SqlValidator,
    ValidatedQuery,
)


class AgentUnavailableError(RuntimeError):
    pass


class AgentWorkflow:
    def __init__(
        self,
        *,
        model: PlanningModel,
        validator: SqlValidator,
        executor: QueryExecutor,
        geography: GeographyScopeRepository | None = None,
        audit: AuditLogger,
        max_repairs: int,
        request_timeout_seconds: float = 42.0,
        summary_timeout_seconds: float = 6.0,
    ) -> None:
        self.model = model
        self.validator = validator
        self.executor = executor
        self.geography = geography
        self.audit = audit
        self.max_repairs = max_repairs
        self.request_timeout_seconds = request_timeout_seconds
        self.summary_timeout_seconds = summary_timeout_seconds

    async def run(
        self,
        *,
        question: str,
        conversation: list[ConversationTurn],
        user: UserContext,
        include_sql: bool,
        request_id: str,
    ) -> ChatResponse:
        started = perf_counter()
        context = PlanningContext(
            request_id=request_id,
            question=question,
            conversation=conversation,
            user=user,
            schema_context=role_safe_schema(user.role),
        )

        planning_started = perf_counter()
        try:
            plan = await self.model.plan(context)
        except PlanningModelError as error:
            planning_ms = self._elapsed_ms(planning_started)
            self._record(
                request_id=request_id,
                user=user,
                outcome="error",
                started=started,
                row_count=0,
                error_code="model_unavailable",
                planning_ms=planning_ms,
            )
            raise AgentUnavailableError("The analytics model is unavailable") from error
        planning_ms = self._elapsed_ms(planning_started)

        if plan.decision is not PlanDecision.QUERY:
            status = (
                ChatStatus.DENIED
                if plan.decision is PlanDecision.DENIED
                else ChatStatus.CLARIFICATION
            )
            self._record(
                request_id=request_id,
                user=user,
                outcome=status.value,
                started=started,
                row_count=0,
                error_code=(
                    "agent_access_decision"
                    if status is ChatStatus.DENIED
                    else "agent_clarification"
                ),
                planning_ms=planning_ms,
            )
            return ChatResponse(
                status=status,
                answer=plain_business_text(
                    plan.response or "Please clarify the requested analysis."
                ),
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )

        preflight = ConversationOutcomeClassifier.before_execution(plan, user=user)
        if preflight is None and plan.geography is not None and self.geography is not None:
            try:
                within_scope = await self.geography.is_within_scope(plan.geography, user=user)
            except Exception as error:
                preflight = ConversationOutcomeClassifier.classify_execution_error(error)
            else:
                if within_scope is False:
                    preflight = ConversationOutcomeClassifier.outside_scope(user)
        if preflight is not None:
            self._record(
                request_id=request_id,
                user=user,
                outcome=preflight.status.value,
                started=started,
                row_count=0,
                error_code=preflight.error_code,
                planning_ms=planning_ms,
            )
            return ChatResponse(
                status=preflight.status,
                answer=preflight.answer,
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )

        validated: ValidatedQuery | None = None
        validation_issues: list[str] = []
        repair_count = 0
        for attempt in range(self.max_repairs + 1):
            try:
                validated = self.validator.validate(
                    plan,
                    role=user.role,
                )
                break
            except SqlValidationError as error:
                if isinstance(error, MissingMarketContextError):
                    self._record(
                        request_id=request_id,
                        user=user,
                        outcome=ChatStatus.CLARIFICATION.value,
                        started=started,
                        row_count=0,
                        error_code="market_context_required",
                        repair_count=repair_count,
                        planning_ms=planning_ms,
                    )
                    return ChatResponse(
                        status=ChatStatus.CLARIFICATION,
                        answer=(
                            "Which product or therapeutic market should I use for market share?"
                        ),
                        assumptions=[self._scope_assumption(user)],
                        request_id=request_id,
                    )
                validation_issues = error.issues
                if attempt >= self.max_repairs:
                    break
                repair_count += 1
                repair_started = perf_counter()
                try:
                    plan = await self.model.repair(context, plan, validation_issues)
                except PlanningModelError:
                    planning_ms += self._elapsed_ms(repair_started)
                    break
                planning_ms += self._elapsed_ms(repair_started)

        if validated is None:
            self._record(
                request_id=request_id,
                user=user,
                outcome="rejected",
                started=started,
                row_count=0,
                error_code="sql_validation",
                repair_count=repair_count,
                planning_ms=planning_ms,
            )
            return ChatResponse(
                status=ChatStatus.REJECTED,
                answer=(
                    "I couldn't complete that analysis as asked. Please rephrase it with "
                    "a metric and time period."
                ),
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )

        execution_started = perf_counter()
        try:
            result = await self.executor.execute(validated, user=user)
        except UnknownProductError as error:
            execution_ms = self._elapsed_ms(execution_started)
            failure = ConversationOutcomeClassifier.unknown_product(error.product_name)
            self._record(
                request_id=request_id,
                user=user,
                outcome=failure.status.value,
                started=started,
                row_count=0,
                error_code=failure.error_code,
                sql_fingerprint=validated.fingerprint,
                repair_count=repair_count,
                planning_ms=planning_ms,
                execution_ms=execution_ms,
            )
            return ChatResponse(
                status=failure.status,
                answer=failure.answer,
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )
        except Exception as error:
            execution_ms = self._elapsed_ms(execution_started)
            failure = ConversationOutcomeClassifier.classify_execution_error(error)
            self._record(
                request_id=request_id,
                user=user,
                outcome="error",
                started=started,
                row_count=0,
                error_code=failure.error_code,
                sql_fingerprint=validated.fingerprint,
                repair_count=repair_count,
                planning_ms=planning_ms,
                execution_ms=execution_ms,
            )
            return ChatResponse(
                status=failure.status,
                answer=failure.answer,
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )

        execution_ms = self._elapsed_ms(execution_started)
        no_data = ConversationOutcomeClassifier.classify_result(result)
        if no_data is not None:
            self._record(
                request_id=request_id,
                user=user,
                outcome=no_data.status.value,
                started=started,
                row_count=len(result.rows),
                error_code=no_data.error_code,
                sql_fingerprint=validated.fingerprint,
                repair_count=repair_count,
                planning_ms=planning_ms,
                execution_ms=execution_ms,
            )
            return ChatResponse(
                status=no_data.status,
                answer=no_data.answer,
                assumptions=self._ordered_unique(
                    [
                        *ConversationOutcomeClassifier.business_notes(plan.assumptions),
                        self._scope_assumption(user),
                    ]
                ),
                sql=validated.sql if include_sql else None,
                request_id=request_id,
            )

        summary_started = perf_counter()
        summary = await self._summarize(context, plan, result)
        summary_ms = self._elapsed_ms(summary_started)
        assumptions = self._ordered_unique(
            [
                *ConversationOutcomeClassifier.business_notes(plan.assumptions),
                self._scope_assumption(user),
                *ConversationOutcomeClassifier.business_notes(summary.notes),
            ]
        )
        self._record(
            request_id=request_id,
            user=user,
            outcome="success",
            started=started,
            row_count=len(result.rows),
            sql_fingerprint=validated.fingerprint,
            repair_count=repair_count,
            planning_ms=planning_ms,
            execution_ms=execution_ms,
            summary_ms=summary_ms,
        )
        return ChatResponse(
            status=ChatStatus.ANSWERED,
            answer=summary.answer,
            columns=result.columns,
            rows=result.rows,
            assumptions=assumptions,
            sql=validated.sql if include_sql else None,
            request_id=request_id,
        )

    async def _summarize(
        self,
        context: PlanningContext,
        plan: AnalyticsPlan,
        result: QueryResult,
    ) -> AnswerSummary:
        try:
            async with asyncio.timeout(self.summary_timeout_seconds):
                summary = await self.model.summarize(context, plan, result)
            answer = plain_business_text(summary.answer)
            if answer and ConversationOutcomeClassifier.is_business_friendly(answer):
                return AnswerSummary(
                    answer=answer,
                    notes=[plain_business_text(note) for note in summary.notes],
                )
        except (PlanningModelError, TimeoutError):
            pass
        return AnswerSummary(
            answer="I found the requested information and included it below.",
            notes=[],
        )

    @staticmethod
    def _scope_assumption(user: UserContext) -> str:
        if user.territory_name:
            return f"Showing results for your assigned territory: {user.territory_name}."
        if user.region_name:
            return f"Showing results for your assigned region: {user.region_name}."
        return "Showing company-wide results."

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    def _record(
        self,
        *,
        request_id: str,
        user: UserContext,
        outcome: str,
        started: float,
        row_count: int,
        error_code: str | None = None,
        sql_fingerprint: str | None = None,
        repair_count: int | None = None,
        planning_ms: float | None = None,
        execution_ms: float | None = None,
        summary_ms: float | None = None,
    ) -> None:
        self.audit.record(
            AuditEvent(
                request_id=request_id,
                user_id=user.user_id,
                action="agent.query",
                role=user.role.value,
                outcome=outcome,
                duration_ms=round((perf_counter() - started) * 1_000, 3),
                row_count=row_count,
                error_code=error_code,
                sql_fingerprint=sql_fingerprint,
                repair_count=repair_count,
                planning_ms=planning_ms,
                execution_ms=execution_ms,
                summary_ms=summary_ms,
            )
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((perf_counter() - started) * 1_000, 3)
