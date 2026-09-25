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
from app.sql.validator import SqlValidationError, SqlValidator, ValidatedQuery


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
    ) -> None:
        self.model = model
        self.validator = validator
        self.executor = executor
        self.geography = geography
        self.audit = audit
        self.max_repairs = max_repairs

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
            question=question,
            conversation=conversation,
            user=user,
            schema_context=role_safe_schema(user.role),
        )

        try:
            plan = await self.model.plan(context)
        except PlanningModelError as error:
            self._record(
                request_id=request_id,
                user=user,
                outcome="error",
                started=started,
                row_count=0,
                error_code="model_unavailable",
            )
            raise AgentUnavailableError("The analytics model is unavailable") from error

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
                validation_issues = error.issues
                if attempt >= self.max_repairs:
                    break
                repair_count += 1
                try:
                    plan = await self.model.repair(context, plan, validation_issues)
                except PlanningModelError:
                    break

        if validated is None:
            self._record(
                request_id=request_id,
                user=user,
                outcome="rejected",
                started=started,
                row_count=0,
                error_code="sql_validation",
                repair_count=repair_count,
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

        try:
            result = await self.executor.execute(validated, user=user)
        except UnknownProductError as error:
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
            )
            return ChatResponse(
                status=failure.status,
                answer=failure.answer,
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )
        except Exception as error:
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
            )
            return ChatResponse(
                status=failure.status,
                answer=failure.answer,
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )

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

        summary = await self._summarize(context, plan, result)
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
            summary = await self.model.summarize(context, plan, result)
            answer = plain_business_text(summary.answer)
            if answer and ConversationOutcomeClassifier.is_business_friendly(answer):
                return AnswerSummary(
                    answer=answer,
                    notes=[plain_business_text(note) for note in summary.notes],
                )
        except PlanningModelError:
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
            )
        )
