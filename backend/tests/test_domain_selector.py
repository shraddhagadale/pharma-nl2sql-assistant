from pathlib import Path

import pytest
import yaml

from app.domain.catalog import CatalogRepository
from app.domain.selector import DomainRuleSelector
from app.models import UserRole

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG = CatalogRepository.load(
    PROJECT_ROOT / "domain" / "domain_catalog.yaml",
    project_root=PROJECT_ROOT,
)
GOLDEN_EXAMPLES = yaml.safe_load(
    (PROJECT_ROOT / "domain" / "golden_examples.yaml").read_text(encoding="utf-8")
)["examples"]


@pytest.mark.parametrize(
    "example",
    GOLDEN_EXAMPLES,
    ids=[example["id"] for example in GOLDEN_EXAMPLES],
)
def test_golden_domain_selection(example: dict) -> None:
    selection = DomainRuleSelector(CATALOG).select(
        example["question"],
        role=UserRole(example["role"]),
    )
    actual = selection.model_dump(mode="json")

    for key, expected_value in example["expected"].items():
        assert actual[key] == expected_value


def test_blank_question_is_rejected() -> None:
    with pytest.raises(ValueError, match="question must not be blank"):
        DomainRuleSelector(CATALOG).select("   ", role=UserRole.EXEC)


def test_follow_up_inherits_only_missing_domain_slots() -> None:
    selection = DomainRuleSelector(CATALOG).select(
        "What about last month?",
        role=UserRole.RAM,
        context_question="Show paid demand by territory for the last 3 months.",
    )

    assert selection.metric_ids == ["paid_demand"]
    assert selection.time_window_id == "last_month"
    assert selection.comparison_time_window_ids == []
    assert selection.dimension_ids == ["territory"]
