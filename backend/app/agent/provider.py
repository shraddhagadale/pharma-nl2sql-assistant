import json
import logging
from time import perf_counter
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError
from pydantic import SecretStr

from app.agent.models import (
    AnalyticsPlan,
    AnswerSummary,
    PlanDecision,
    PlanningContext,
    QueryResult,
)
from app.agent.prompts import (
    PLANNER_INSTRUCTIONS,
    REPAIR_INSTRUCTIONS,
    SUMMARY_INSTRUCTIONS,
    planning_input,
    repair_input,
    summary_input,
)
from app.domain.knowledge import DomainKnowledgeError, DomainKnowledgeRepository

MAX_DOMAIN_TOOL_CALLS = 3
PREFETCHED_DOMAIN_SECTIONS = 6
GROUNDING_SEARCH_CONTEXT = "metric definition time period offsets data source hierarchy security"

logger = logging.getLogger("pharma.model")


class PlanningModelError(RuntimeError):
    def __init__(self, message: str, *, code: str = "planning_model_error") -> None:
        self.code = code
        super().__init__(message)


class PlanningModel(Protocol):
    async def plan(self, context: PlanningContext) -> AnalyticsPlan: ...

    async def repair(
        self,
        context: PlanningContext,
        prior_plan: AnalyticsPlan,
        issues: list[str],
    ) -> AnalyticsPlan: ...

    async def summarize(
        self,
        context: PlanningContext,
        plan: AnalyticsPlan,
        result: QueryResult,
    ) -> AnswerSummary: ...


class UnavailablePlanningModel:
    async def plan(self, context: PlanningContext) -> AnalyticsPlan:
        raise PlanningModelError("No model API key is configured", code="model_not_configured")

    async def repair(
        self,
        context: PlanningContext,
        prior_plan: AnalyticsPlan,
        issues: list[str],
    ) -> AnalyticsPlan:
        raise PlanningModelError("No model API key is configured", code="model_not_configured")

    async def summarize(
        self,
        context: PlanningContext,
        plan: AnalyticsPlan,
        result: QueryResult,
    ) -> AnswerSummary:
        raise PlanningModelError("No model API key is configured", code="model_not_configured")


class OpenAIPlanningModel:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        reasoning_effort: str,
        domain_knowledge: DomainKnowledgeRepository,
        request_timeout_seconds: float = 20.0,
    ) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            timeout=request_timeout_seconds,
            max_retries=1,
        )
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.domain_knowledge = domain_knowledge

    async def plan(self, context: PlanningContext) -> AnalyticsPlan:
        grounding = self._prefetch_grounding(context)
        return await self._parse_with_domain_tools(
            instructions=PLANNER_INSTRUCTIONS,
            content=planning_input(context, grounding),
            context=context,
            grounding=grounding,
            operation="plan",
        )

    async def repair(
        self,
        context: PlanningContext,
        prior_plan: AnalyticsPlan,
        issues: list[str],
    ) -> AnalyticsPlan:
        grounding = self._prefetch_grounding(context)
        return await self._parse_with_domain_tools(
            instructions=f"{PLANNER_INSTRUCTIONS}\n\n{REPAIR_INSTRUCTIONS}",
            content=repair_input(context, prior_plan, issues, grounding),
            context=context,
            grounding=grounding,
            operation="repair",
        )

    async def summarize(
        self,
        context: PlanningContext,
        plan: AnalyticsPlan,
        result: QueryResult,
    ) -> AnswerSummary:
        return await self._parse(
            instructions=SUMMARY_INSTRUCTIONS,
            content=summary_input(context, plan, result),
            output_type=AnswerSummary,
            request_id=context.request_id,
            operation="summarize",
        )

    async def _parse(
        self,
        *,
        instructions: str,
        content: str,
        output_type,
        request_id: str,
        operation: str,
    ):
        started = perf_counter()
        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=instructions,
                input=content,
                text_format=output_type,
                reasoning={"effort": self.reasoning_effort},
                max_output_tokens=4_000,
                store=False,
            )
        except OpenAIError as error:
            self._log_model_call(
                request_id=request_id,
                operation=operation,
                round_number=1,
                started=started,
                outcome="error",
                error_type=type(error).__name__,
            )
            raise PlanningModelError(
                "The model request failed",
                code="provider_request_failed",
            ) from error

        self._log_model_call(
            request_id=request_id,
            operation=operation,
            round_number=1,
            started=started,
            outcome="success",
            response_id=getattr(response, "id", None),
        )

        parsed = response.output_parsed
        if parsed is None:
            raise PlanningModelError(
                "The model returned no structured output",
                code="invalid_structured_output",
            )
        return parsed

    async def _parse_with_domain_tools(
        self,
        *,
        instructions: str,
        content: str,
        context: PlanningContext,
        grounding: list[dict[str, str]],
        operation: str,
    ) -> AnalyticsPlan:
        input_items: list[object] = [{"role": "user", "content": content}]
        observed_sections = {(section["document"], section["heading"]) for section in grounding}
        tool_calls_used = 0

        for response_round in range(MAX_DOMAIN_TOOL_CALLS + 1):
            started = perf_counter()
            try:
                response = await self.client.responses.parse(
                    model=self.model,
                    instructions=instructions,
                    input=input_items,
                    tools=self.domain_knowledge.tool_definitions,
                    tool_choice="auto",
                    parallel_tool_calls=False,
                    text_format=AnalyticsPlan,
                    reasoning={"effort": self.reasoning_effort},
                    max_output_tokens=4_000,
                    store=False,
                )
            except OpenAIError as error:
                self._log_model_call(
                    request_id=context.request_id,
                    operation=operation,
                    round_number=response_round + 1,
                    started=started,
                    outcome="error",
                    error_type=type(error).__name__,
                )
                raise PlanningModelError(
                    "The model request failed",
                    code="provider_request_failed",
                ) from error

            self._log_model_call(
                request_id=context.request_id,
                operation=operation,
                round_number=response_round + 1,
                started=started,
                outcome="success",
                response_id=getattr(response, "id", None),
            )

            tool_calls = [item for item in response.output if item.type == "function_call"]
            if not tool_calls:
                plan = response.output_parsed
                if plan is None:
                    raise PlanningModelError(
                        "The model returned no structured output",
                        code="invalid_structured_output",
                    )
                if plan.decision is PlanDecision.QUERY:
                    cited = {(item.document, item.heading) for item in plan.evidence}
                    if not cited:
                        raise PlanningModelError(
                            "The analytics plan did not cite domain knowledge",
                            code="missing_grounding_citation",
                        )
                    if not cited.issubset(observed_sections):
                        raise PlanningModelError(
                            "The analytics plan cited unread domain knowledge",
                            code="invalid_grounding_citation",
                        )
                return plan

            if tool_calls_used + len(tool_calls) > MAX_DOMAIN_TOOL_CALLS:
                raise PlanningModelError(
                    "The model exceeded the domain knowledge tool limit",
                    code="domain_tool_limit",
                )
            tool_calls_used += len(tool_calls)
            input_items.extend(response.output)
            for tool_call in tool_calls:
                try:
                    arguments = json.loads(tool_call.arguments)
                    if not isinstance(arguments, dict):
                        raise DomainKnowledgeError("tool arguments must be an object")
                    result = self.domain_knowledge.call_tool(tool_call.name, arguments)
                    self._record_observed_sections(result, observed_sections)
                except (DomainKnowledgeError, json.JSONDecodeError) as error:
                    result = {"error": str(error)}
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": json.dumps(result, sort_keys=True),
                    }
                )
        raise PlanningModelError(
            "The model did not return a final analytics plan",
            code="incomplete_tool_loop",
        )

    def _prefetch_grounding(self, context: PlanningContext) -> list[dict[str, str]]:
        recent_user_turns = [
            turn.content for turn in context.conversation if turn.role.value == "user"
        ][-4:]
        query = " ".join([*recent_user_turns, context.question, GROUNDING_SEARCH_CONTEXT])
        return [
            section.as_result()
            for section in self.domain_knowledge.search_diverse(
                query,
                limit=PREFETCHED_DOMAIN_SECTIONS,
            )
        ]

    @staticmethod
    def _log_model_call(
        *,
        request_id: str,
        operation: str,
        round_number: int,
        started: float,
        outcome: str,
        response_id: str | None = None,
        error_type: str | None = None,
    ) -> None:
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "action": "model.response",
                    "operation": operation,
                    "round": round_number,
                    "outcome": outcome,
                    "duration_ms": round((perf_counter() - started) * 1_000, 3),
                    "response_id": response_id,
                    "error_type": error_type,
                },
                sort_keys=True,
            )
        )

    @staticmethod
    def _record_observed_sections(
        result: dict[str, object],
        observed: set[tuple[str, str]],
    ) -> None:
        candidates: list[object]
        raw_results = result.get("results")
        if isinstance(raw_results, list):
            candidates = raw_results
        else:
            candidates = [result]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            document = candidate.get("document")
            heading = candidate.get("heading")
            if isinstance(document, str) and isinstance(heading, str):
                observed.add((document, heading))
