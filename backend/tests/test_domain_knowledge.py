from pathlib import Path

import pytest

from app.domain.knowledge import (
    DOMAIN_DOCUMENTS,
    DomainKnowledgeError,
    DomainKnowledgeRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def knowledge() -> DomainKnowledgeRepository:
    return DomainKnowledgeRepository(PROJECT_ROOT / "docs")


def test_repository_loads_only_authoritative_domain_documents(
    knowledge: DomainKnowledgeRepository,
) -> None:
    assert knowledge.documents == DOMAIN_DOCUMENTS
    assert "architecture.md" not in knowledge.documents


def test_search_returns_markdown_sections_for_metric_and_period(
    knowledge: DomainKnowledgeRepository,
) -> None:
    results = knowledge.search("free drug hub dispense pack units last week offsets", limit=6)
    locations = {(item.document, item.heading) for item in results}

    assert any(document == "data_source_guide.md" for document, _ in locations)
    assert any(document == "period_offsets.md" for document, _ in locations)


def test_diverse_search_covers_account_and_period_documents(
    knowledge: DomainKnowledgeRepository,
) -> None:
    results = knowledge.search_diverse(
        "Rank the top 10 accounts by pack units last quarter. "
        "metric definition time period offsets data source hierarchy security",
        limit=6,
    )
    documents = [item.document for item in results]

    assert "account_analytics.md" in documents
    assert "period_offsets.md" in documents
    assert any(item.heading == "Common Time Windows" for item in results)
    assert max(documents.count(document) for document in set(documents)) <= 2


def test_read_returns_exact_section_with_digest(
    knowledge: DomainKnowledgeRepository,
) -> None:
    section = knowledge.read("period_offsets.md", "`wk_offset` — Week Offset")

    assert "`1` = last week" in section.content
    assert len(section.sha256) == 64


def test_read_rejects_unknown_documents_and_headings(
    knowledge: DomainKnowledgeRepository,
) -> None:
    with pytest.raises(DomainKnowledgeError, match="unknown domain document"):
        knowledge.read("../DESIGN.md", "Domain knowledge")
    with pytest.raises(DomainKnowledgeError, match="unknown heading"):
        knowledge.read("period_offsets.md", "Not a real heading")


def test_tools_are_strict_and_bounded(knowledge: DomainKnowledgeRepository) -> None:
    tools = {tool["name"]: tool for tool in knowledge.tool_definitions}

    assert set(tools) == {"search_domain_knowledge", "read_domain_section"}
    assert tools["search_domain_knowledge"]["strict"] is True
    with pytest.raises(DomainKnowledgeError, match="between 1 and 6"):
        knowledge.search("paid demand", limit=7)
