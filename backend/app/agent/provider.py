from typing import Protocol

from openai import AsyncOpenAI, OpenAIError
from pydantic import SecretStr

from app.agent.models import AnalyticsPlan, AnswerSummary, PlanningContext, QueryResult
from app.agent.prompts import (
    PLANNER_INSTRUCTIONS,
    REPAIR_INSTRUCTIONS,
    SUMMARY_INSTRUCTIONS,
    planning_input,
    repair_input,
    summary_input,
)


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
    def __init__(self, *, api_key: SecretStr, model: str, reasoning_effort: str) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            timeout=30.0,
            max_retries=1,
        )
        self.model = model
        self.reasoning_effort = reasoning_effort

    async def plan(self, context: PlanningContext) -> AnalyticsPlan:
        return await self._parse(
            instructions=PLANNER_INSTRUCTIONS,
            content=planning_input(context),
            output_type=AnalyticsPlan,
        )

    async def repair(
        self,
        context: PlanningContext,
        prior_plan: AnalyticsPlan,
        issues: list[str],
    ) -> AnalyticsPlan:
        return await self._parse(
            instructions=f"{PLANNER_INSTRUCTIONS}\n\n{REPAIR_INSTRUCTIONS}",
            content=repair_input(context, prior_plan, issues),
            output_type=AnalyticsPlan,
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
