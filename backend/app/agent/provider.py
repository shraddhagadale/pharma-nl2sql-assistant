import json
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

MAX_DOMAIN_TOOL_CALLS = 6


class PlanningModelError(RuntimeError):
    pass


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
        raise PlanningModelError("No model API key is configured")

    async def repair(
        self,
        context: PlanningContext,
        prior_plan: AnalyticsPlan,
        issues: list[str],
    ) -> AnalyticsPlan:
        raise PlanningModelError("No model API key is configured")

    async def summarize(
        self,
        context: PlanningContext,
        plan: AnalyticsPlan,
        result: QueryResult,
    ) -> AnswerSummary:
        raise PlanningModelError("No model API key is configured")


class OpenAIPlanningModel:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        reasoning_effort: str,
        domain_knowledge: DomainKnowledgeRepository,
    ) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            timeout=30.0,
            max_retries=1,
        )
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.domain_knowledge = domain_knowledge

    async def plan(self, context: PlanningContext) -> AnalyticsPlan:
        return await self._parse_with_domain_tools(
            instructions=PLANNER_INSTRUCTIONS,
            content=planning_input(context),
        )

    async def repair(
        self,
        context: PlanningContext,
        prior_plan: AnalyticsPlan,
        issues: list[str],
    ) -> AnalyticsPlan:
        return await self._parse_with_domain_tools(
            instructions=f"{PLANNER_INSTRUCTIONS}\n\n{REPAIR_INSTRUCTIONS}",
            content=repair_input(context, prior_plan, issues),
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
        )

    async def _parse(self, *, instructions: str, content: str, output_type):
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
            raise PlanningModelError("The model request failed") from error

        parsed = response.output_parsed
        if parsed is None:
            raise PlanningModelError("The model returned no structured output")
        return parsed

    async def _parse_with_domain_tools(
        self,
        *,
        instructions: str,
        content: str,
    ) -> AnalyticsPlan:
        input_items: list[object] = [{"role": "user", "content": content}]
        observed_sections: set[tuple[str, str]] = set()
        tool_calls_used = 0

        for response_round in range(MAX_DOMAIN_TOOL_CALLS + 1):
            try:
                response = await self.client.responses.parse(
                    model=self.model,
                    instructions=instructions,
                    input=input_items,
                    tools=self.domain_knowledge.tool_definitions,
                    tool_choice=(
                        {"type": "function", "name": "search_domain_knowledge"}
                        if response_round == 0
                        else "auto"
                    ),
                    parallel_tool_calls=False,
                    text_format=AnalyticsPlan,
                    reasoning={"effort": self.reasoning_effort},
                    max_output_tokens=4_000,
                    store=False,
                )
            except OpenAIError as error:
                raise PlanningModelError("The model request failed") from error

            tool_calls = [item for item in response.output if item.type == "function_call"]
            if not tool_calls:
                plan = response.output_parsed
                if plan is None:
                    raise PlanningModelError("The model returned no structured output")
                if plan.decision is PlanDecision.QUERY:
                    cited = {(item.document, item.heading) for item in plan.evidence}
                    if not cited:
                        raise PlanningModelError("The analytics plan did not cite domain knowledge")
                    if not cited.issubset(observed_sections):
                        raise PlanningModelError("The analytics plan cited unread domain knowledge")
                return plan

            if tool_calls_used + len(tool_calls) > MAX_DOMAIN_TOOL_CALLS:
                raise PlanningModelError("The model exceeded the domain knowledge tool limit")
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
        raise PlanningModelError("The model did not return a final analytics plan")

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
