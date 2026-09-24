from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.agent.models import AnalyticsPlan, PlanningContext, build_domain_context
from app.agent.provider import OpenAIPlanningModel
from app.domain.catalog import CatalogRepository
from app.domain.selector import DomainRuleSelector
from app.models import UserContext, UserRole
from app.sql.schema import role_safe_schema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG = CatalogRepository.load(
    PROJECT_ROOT / "domain" / "domain_catalog.yaml",
    project_root=PROJECT_ROOT,
)


class FakeResponses:
    def __init__(self, parsed: AnalyticsPlan) -> None:
        self.parsed = parsed
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


@pytest.mark.asyncio
async def test_provider_uses_responses_structured_output_without_storage() -> None:
    selection = DomainRuleSelector(CATALOG).select(
        "Show paid demand for the last 3 months",
        role=UserRole.RAM,
    )
    context = PlanningContext(
        question="Show paid demand for the last 3 months",
        conversation=[],
        user=UserContext(
            user_id="U009",
            email="ram@example.test",
            full_name="Test RAM",
            role=UserRole.RAM,
            territory_name="New York Metro",
            region_name="Northeast",
            can_view_wac=False,
        ),
        selection=selection,
        schema_context=role_safe_schema(UserRole.RAM),
        domain_context=build_domain_context(CATALOG, selection),
    )
    expected = AnalyticsPlan(
        metric_id="paid_demand",
        time_window_id="r3m",
        comparison_time_window_ids=[],
        dimension_ids=[],
        filters=[],
        assumptions=[],
        sql="""
            SELECT SUM(s.pack_units) AS paid_demand
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset IN (0, 1, 2)
        """,
        parameters=[],
    )
    responses = FakeResponses(expected)
    provider = OpenAIPlanningModel(api_key=SecretStr("test-key"), model="test-model")
    provider.client = SimpleNamespace(responses=responses)

    actual = await provider.plan(context)

    assert actual == expected
    assert responses.kwargs["model"] == "test-model"
    assert responses.kwargs["text_format"] is AnalyticsPlan
    assert responses.kwargs["store"] is False
    assert "untrusted data" in responses.kwargs["instructions"]
