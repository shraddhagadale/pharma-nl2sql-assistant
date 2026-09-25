# Markdown Domain Knowledge

The supplied pharmaceutical Markdown documents are the application's only
runtime source of business meaning. There is no secondary YAML catalog and no
manual synonym registry.

## Approved document set

The domain service loads these files from `docs/` at application startup:

- `account_analytics.md`
- `data_source_guide.md`
- `market_classification.md`
- `metric_definitions.md`
- `org_hierarchy.md`
- `period_offsets.md`
- `product_analytics.md`
- `security_model.md`

Architecture, deployment, and operational documents are deliberately excluded
from model retrieval.

## Retrieval

Each approved document is divided into heading-bounded sections. The in-memory
search index scores normalized query terms using heading matches, section term
frequency, inverse section frequency, and exact-phrase matches. The corpus is
small enough that this requires no vector database or external service. The
backend prefetches the four best sections from the current question and recent
user turns so straightforward requests do not require an extra model/tool
round trip.

The model receives two bounded function tools:

- `search_domain_knowledge(query, limit)` returns at most six relevant sections.
- `read_domain_section(document, heading)` returns one exact approved section.

Every prefetched or tool-returned result contains the document name, heading,
content, and SHA-256 digest.
Paths outside the allowlisted corpus and unknown headings fail closed.

## Planner contract

The first planning round requires a domain-knowledge tool call. Before returning
SQL, the model resolves the current message against the recent conversation,
including previous requests that timed out, and rewrites it as a standalone
business question. A query plan must cite at least one document/heading pair
actually returned during that tool loop; missing or invented evidence is
rejected.

The Markdown content is reference data, not executable instructions. It cannot
change the authenticated role, database pool, geographic scope, SQL policy, RLS,
or WAC privileges.

## Document updates

Edit the authoritative Markdown file directly, review the change, run the domain
knowledge and backend test suites, and redeploy. The index and section digests are
rebuilt on application startup, so no generated catalog or provenance refresh is
required.

```bash
backend/.venv/bin/python -m pytest backend/tests/test_domain_knowledge.py
backend/.venv/bin/python -m pytest backend/tests
```

Live model evaluation remains necessary for paraphrases, multi-turn reference
resolution, retrieval quality, and formula accuracy. Deterministic tests remain
responsible for SQL structure, role-visible columns, parameters, timeouts, result
bounds, and database enforcement.
