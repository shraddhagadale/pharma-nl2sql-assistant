from time import perf_counter

from app.agent.models import (
    AnalyticsPlan,
    AnswerSummary,
    PlanningContext,
    QueryResult,
    build_domain_context,
)
from app.agent.provider import PlanningModel, PlanningModelError
from app.audit import AuditEvent, AuditLogger
from app.domain.models import DomainCatalog
from app.domain.selector import DomainRuleSelector, SelectionStatus
from app.models import (
    ChatResponse,
    ChatStatus,
    ConversationRole,
    ConversationTurn,
    UserContext,
)
from app.sql.executor import QueryExecutor
from app.sql.schema import role_safe_schema
from app.sql.validator import SqlValidationError, SqlValidator, ValidatedQuery


class AgentUnavailableError(RuntimeError):
    pass


class AgentWorkflow:
    def __init__(
        self,
        *,
        catalog: DomainCatalog,
        model: PlanningModel,
        validator: SqlValidator,
        executor: QueryExecutor,
        audit: AuditLogger,
        max_repairs: int,
    ) -> None:
        self.catalog = catalog
        self.selector = DomainRuleSelector(catalog)
        self.model = model
        self.validator = validator
        self.executor = executor
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
        selection = self.selector.select(
            question,
            role=user.role,
            context_question=self._selection_context(question, conversation),
        )
        context = PlanningContext(
            question=question,
            conversation=conversation,
            user=user,
            selection=selection,
            schema_context=role_safe_schema(user.role),
            domain_context=build_domain_context(self.catalog, selection),
        )

        if selection.status is SelectionStatus.DENIED:
            answer = selection.denied_reason or "This request is not available for your role."
            if selection.alternative_metric_id:
                alternative = self.catalog.metrics_by_id[selection.alternative_metric_id]
                answer += f" I can show {alternative.label.lower()} instead."
            self._record(
                request_id=request_id,
                user=user,
                outcome="denied",
                started=started,
                row_count=0,
                error_code="role_policy",
            )
            return ChatResponse(
                status=ChatStatus.DENIED,
                answer=answer,
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
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

        validated: ValidatedQuery | None = None
        validation_issues: list[str] = []
        repair_count = 0
        for attempt in range(self.max_repairs + 1):
            try:
                validated = self.validator.validate(
                    plan,
                    role=user.role,
                    catalog=self.catalog,
                    selection=selection,
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
                    "I couldn't produce a query that passed the safety and business-rule "
                    "checks. Please rephrase the question with a metric and time period."
                ),
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )

        try:
            result = await self.executor.execute(validated, user=user)
        except Exception:
            self._record(
                request_id=request_id,
                user=user,
                outcome="error",
                started=started,
                row_count=0,
                error_code="database_error",
                sql_fingerprint=validated.fingerprint,
                repair_count=repair_count,
            )
            return ChatResponse(
                status=ChatStatus.REJECTED,
                answer="The validated query could not be completed safely. Please try again.",
                assumptions=[self._scope_assumption(user)],
                request_id=request_id,
            )

        summary = await self._summarize(context, plan, result)
        assumptions = self._ordered_unique(
            [*plan.assumptions, self._scope_assumption(user), *summary.notes]
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
            if summary.answer.strip():
                return summary
        except PlanningModelError:
            pass
        if not result.rows:
            return AnswerSummary(
                answer="No matching data was found for that request.",
                notes=["The query completed successfully with no result rows."],
            )
        return AnswerSummary(
            answer=f"The query returned {len(result.rows)} result row(s).",
            notes=["The narrative summary was unavailable; the validated table is shown."],
        )

    @staticmethod
    def _selection_context(
        question: str,
        conversation: list[ConversationTurn],
    ) -> str | None:
        normalized = question.casefold().strip()
        follow_up_markers = (
            "what about",
            "how about",
            "and last",
            "instead",
            "same ",
            "those ",
            "them ",
        )
        if not any(marker in normalized for marker in follow_up_markers):
            return None
        return next(
            (turn.content for turn in reversed(conversation) if turn.role is ConversationRole.USER),
            None,
        )

    @staticmethod
    def _scope_assumption(user: UserContext) -> str:
        if user.territory_name:
            return f"Results are limited by database RLS to {user.territory_name}."
        if user.region_name:
            return f"Results are limited by database RLS to {user.region_name}."
        return "Results use the executive global database scope."

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
