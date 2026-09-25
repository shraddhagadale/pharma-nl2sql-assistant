import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.domain.markdown import HEADING_PATTERN, extract_section

DOMAIN_DOCUMENTS = (
    "account_analytics.md",
    "data_source_guide.md",
    "market_classification.md",
    "metric_definitions.md",
    "org_hierarchy.md",
    "period_offsets.md",
    "product_analytics.md",
    "security_model.md",
)
TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


class DomainKnowledgeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeSection:
    document: str
    heading: str
    content: str
    sha256: str
    heading_tokens: tuple[str, ...]
    content_tokens: tuple[str, ...]

    def as_result(self) -> dict[str, str]:
        return {
            "document": self.document,
            "heading": self.heading,
            "content": self.content,
            "sha256": self.sha256,
        }


class DomainKnowledgeRepository:
    def __init__(self, docs_path: Path) -> None:
        self.docs_path = docs_path.resolve()
        self._documents = self._load_documents()
        self._sections = self._load_sections()
        self._document_frequency = self._build_document_frequency()

    @property
    def documents(self) -> tuple[str, ...]:
        return tuple(self._documents)

    @property
    def tool_definitions(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "name": "search_domain_knowledge",
                "description": (
                    "Search the authoritative pharmaceutical business Markdown documents. "
                    "Use this only when the prefetched sections are insufficient for metric "
                    "definitions, time periods, data sources, hierarchy rules, product rules, "
                    "or access semantics. Do not repeat a search covered by prefetched content."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A concise business-domain search query.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 6,
                            "description": "Maximum number of relevant Markdown sections.",
                        },
                    },
                    "required": ["query", "limit"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "type": "function",
                "name": "read_domain_section",
                "description": (
                    "Read one exact Markdown section when a search result needs more detail. "
                    "Use only document and heading values returned by the search tool, and do "
                    "not reread a section already supplied in prefetched content."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document": {"type": "string"},
                        "heading": {"type": "string"},
                    },
                    "required": ["document", "heading"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "search_domain_knowledge":
            query = arguments.get("query")
            limit = arguments.get("limit")
            if not isinstance(query, str) or not isinstance(limit, int):
                raise DomainKnowledgeError("search requires string query and integer limit")
            return {"results": [section.as_result() for section in self.search(query, limit=limit)]}
        if name == "read_domain_section":
            document = arguments.get("document")
            heading = arguments.get("heading")
            if not isinstance(document, str) or not isinstance(heading, str):
                raise DomainKnowledgeError("read requires document and heading strings")
            return self.read(document, heading).as_result()
        raise DomainKnowledgeError(f"unknown domain knowledge tool: {name}")

    def search(self, query: str, *, limit: int = 4) -> list[KnowledgeSection]:
        tokens = self._tokens(query)
        if not tokens:
            raise DomainKnowledgeError("search query must contain words")
        if not 1 <= limit <= 6:
            raise DomainKnowledgeError("search limit must be between 1 and 6")

        token_counts = Counter(tokens)
        scored: list[tuple[float, KnowledgeSection]] = []
        for section in self._sections:
            heading_counts = Counter(section.heading_tokens)
            content_counts = Counter(section.content_tokens)
            score = 0.0
            for token, query_count in token_counts.items():
                frequency = self._document_frequency.get(token, 0)
                inverse_frequency = math.log((len(self._sections) + 1) / (frequency + 1)) + 1
                term_score = 4 * heading_counts[token] + min(content_counts[token], 8)
                score += query_count * inverse_frequency * term_score
            normalized_query = " ".join(tokens)
            if normalized_query and normalized_query in section.content.casefold():
                score += 8
            if score > 0:
                scored.append((score, section))

        scored.sort(key=lambda item: (-item[0], item[1].document, item[1].heading))
        return [section for _, section in scored[:limit]]

    def read(self, document: str, heading: str) -> KnowledgeSection:
        if document not in self._documents:
            raise DomainKnowledgeError(f"unknown domain document: {document}")
        for section in self._sections:
            if section.document == document and section.heading == heading:
                return section
        raise DomainKnowledgeError(f"unknown heading {heading!r} in {document}")

    def _load_documents(self) -> dict[str, Path]:
        if not self.docs_path.is_dir():
            raise DomainKnowledgeError(f"domain docs directory does not exist: {self.docs_path}")
        documents: dict[str, Path] = {}
        for name in DOMAIN_DOCUMENTS:
            path = (self.docs_path / name).resolve()
            if path.parent != self.docs_path or not path.is_file():
                raise DomainKnowledgeError(f"required domain document is missing: {name}")
            documents[name] = path
        return documents

    def _load_sections(self) -> tuple[KnowledgeSection, ...]:
        sections: list[KnowledgeSection] = []
        for document, path in self._documents.items():
            lines = path.read_text(encoding="utf-8").splitlines()
            headings = [
                match.group(2)
                for line in lines
                if (match := HEADING_PATTERN.match(line)) and len(match.group(1)) > 1
            ]
            for heading in headings:
                content = extract_section(path, heading)
                sections.append(
                    KnowledgeSection(
                        document=document,
                        heading=heading,
                        content=content,
                        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        heading_tokens=tuple(self._tokens(heading)),
                        content_tokens=tuple(self._tokens(content)),
                    )
                )
        if not sections:
            raise DomainKnowledgeError("domain documents contain no searchable sections")
        return tuple(sections)

    def _build_document_frequency(self) -> Counter[str]:
        frequency: Counter[str] = Counter()
        for section in self._sections:
            frequency.update(set((*section.heading_tokens, *section.content_tokens)))
        return frequency

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return TOKEN_PATTERN.findall(value.casefold())
