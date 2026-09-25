import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.agent.models import AnalyticsPlan, PlanningContext
from app.agent.provider import OpenAIPlanningModel
from app.domain.knowledge import DomainKnowledgeRepository
from app.models import ConversationRole, ConversationTurn, UserContext, UserRole
from app.sql.schema import role_safe_schema

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeResponses:
    def __init__(self, parsed: AnalyticsPlan) -> None:
        self.parsed = parsed
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="search_domain_knowledge",
                        arguments=json.dumps({"query": "free drug last week", "limit": 4}),
                        call_id="call-1",
                    )
                ],
                output_parsed=None,
            )
        return SimpleNamespace(output=[], output_parsed=self.parsed)


class MultiDocumentResponses:
    def __init__(self, parsed: AnalyticsPlan) -> None:
        self.parsed = parsed
        self.calls: list[dict] = []
        self.queries = (
            "top accounts pack units",
            "account hierarchy grandparent organization",
            "last quarter period offset",
            "ranking account analytics",
        )

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        if index < len(self.queries):
            return SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="search_domain_knowledge",
                        arguments=json.dumps({"query": self.queries[index], "limit": 4}),
                        call_id=f"call-{index + 1}",
                    )
                ],
                output_parsed=None,
            )
        return SimpleNamespace(output=[], output_parsed=self.parsed)


@pytest.mark.asyncio
async def test_provider_uses_markdown_tools_then_structured_output_without_storage() -> None:
    knowledge = DomainKnowledgeRepository(PROJECT_ROOT / "docs")
    evidence = knowledge.search("free drug last week", limit=4)[0]
    context = PlanningContext(
        question="Give me from last week",
        conversation=[
            ConversationTurn(
                role=ConversationRole.USER,
                content="How much free drug did we provide in the last 4 weeks?",
            ),
            ConversationTurn(
                role=ConversationRole.ASSISTANT,
                content="That analysis took too long to complete.",
            ),
        ],
        user=UserContext(
            user_id="U009",
            email="ram@example.test",
            full_name="Test RAM",
            role=UserRole.RAM,
            territory_name="New York Metro",
            region_name="Northeast",
            can_view_wac=False,
        ),
        schema_context=role_safe_schema(UserRole.RAM),
    )
    expected = AnalyticsPlan(
        resolved_question="Show free-drug pack units for last week",
        evidence=[{"document": evidence.document, "heading": evidence.heading}],
        metric_id="free_drug_pack_units",
        time_window_id="last_week",
        sql="""
            SELECT SUM(s.pack_units) AS free_drug_pack_units
            FROM sales AS s
            WHERE s.data_source = 'hub_dispense'
              AND s.wk_offset = 1
        """,
    )
    responses = FakeResponses(expected)
    provider = OpenAIPlanningModel(
        api_key=SecretStr("test-key"),
        model="test-model",
        reasoning_effort="medium",
        domain_knowledge=knowledge,
    )
    provider.client = SimpleNamespace(responses=responses)

    actual = await provider.plan(context)

    assert actual == expected
    assert len(responses.calls) == 2
    assert responses.calls[0]["model"] == "test-model"
    assert responses.calls[0]["reasoning"] == {"effort": "medium"}
    assert responses.calls[0]["text_format"] is AnalyticsPlan
    assert responses.calls[0]["tool_choice"] == {
        "type": "function",
        "name": "search_domain_knowledge",
    }
    assert responses.calls[0]["store"] is False
    assert {tool["name"] for tool in responses.calls[0]["tools"]} == {
        "search_domain_knowledge",
        "read_domain_section",
    }
    second_input = responses.calls[1]["input"]
    assert any(
        isinstance(item, dict) and item.get("type") == "function_call_output"
        for item in second_input
    )
    first_input = responses.calls[0]["input"][0]["content"]
    assert "How much free drug did we provide in the last 4 weeks?" in first_input
    assert "Give me from last week" in first_input
    assert "bounded conversation" in responses.calls[0]["instructions"].casefold()


@pytest.mark.asyncio
async def test_provider_allows_multi_document_research_before_final_plan() -> None:
    knowledge = DomainKnowledgeRepository(PROJECT_ROOT / "docs")
    evidence = knowledge.search("top accounts pack units", limit=4)[0]
    context = PlanningContext(
        question="Rank the top accounts by pack units last quarter.",
        conversation=[],
        user=UserContext(
            user_id="U003",
            email="director@example.test",
            full_name="Test Director",
            role=UserRole.DIRECTOR,
            territory_name=None,
            region_name="Northeast",
            can_view_wac=False,
        ),
        schema_context=role_safe_schema(UserRole.DIRECTOR),
    )
    expected = AnalyticsPlan(
        resolved_question="Rank Northeast accounts by pack units last quarter",
        evidence=[{"document": evidence.document, "heading": evidence.heading}],
        metric_id="pack_units",
        time_window_id="last_quarter",
        dimension_ids=["grandparent_organization"],
        sql="""
            SELECT o.grandparent_org_name, SUM(s.pack_units) AS pack_units
            FROM sales AS s
            JOIN organizations AS o ON o.org_id = s.org_id
            WHERE s.mo_offset BETWEEN 3 AND 5
            GROUP BY o.grandparent_org_name
            ORDER BY pack_units DESC
            LIMIT 10
        """,
    )
    responses = MultiDocumentResponses(expected)
    provider = OpenAIPlanningModel(
        api_key=SecretStr("test-key"),
        model="test-model",
        reasoning_effort="medium",
        domain_knowledge=knowledge,
    )
    provider.client = SimpleNamespace(responses=responses)

    actual = await provider.plan(context)

    assert actual == expected
    assert len(responses.calls) == 5
    assert all(call["tool_choice"] == "auto" for call in responses.calls[1:])
