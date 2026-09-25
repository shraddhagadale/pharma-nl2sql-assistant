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
