# Deterministic Domain Catalog

Phase 6 turns the supplied Markdown business knowledge into a small, typed
operational catalog. It does not use an LLM, embeddings, or a vector database.
The Markdown documents remain the source of truth; the YAML is a reviewed
translation that the later planner can consume without interpreting prose on
every request.

## What the catalog contains

`domain/domain_catalog.yaml` defines:

- metrics and formulas, including market-share numerator and denominator rules;
- time windows based on `wk_offset` and `mo_offset`;
- grouping dimensions and required joins;
- the semantics of distributor, hub-dispense, and market data;
- security metadata, including the executive-only WAC boundary; and
- explicit defaults for otherwise underspecified questions.

The catalog stores structured fields and operators, not executable SQL. SQL
generation and AST validation remain separate Phase 7 responsibilities. RLS
and PostgreSQL privileges continue to be the authoritative security boundary.

## Provenance and drift detection

Every definition points to an exact Markdown heading and stores the SHA-256 of
that section. Catalog loading fails when a source path or heading disappears,
or when the referenced section changes. This prevents a documentation edit
from silently leaving the operational rules stale.

After intentionally changing a source document:

1. update the corresponding structured catalog rule;
2. inspect the differences in both files;
3. preview stale provenance with `./scripts/refresh_domain_provenance.py`;
4. refresh reviewed hashes with `./scripts/refresh_domain_provenance.py --write`;
5. run `./scripts/validate_domain_catalog.py` and the backend tests.

Refreshing a hash is an explicit review action, not automatic catalog
regeneration. Automatically translating changed prose could conceal semantic
errors, while an untracked duplicate YAML source would drift. The digest gate
keeps one human-review point and makes that decision visible in Git.

## Deterministic selection

`DomainRuleSelector` normalizes a question and uses curated synonyms to select
one metric, one time window, and zero or more dimensions. The longest matching
metric and time-window phrase wins; documented defaults apply when no phrase
matches. A non-executive WAC request is denied before SQL generation and points
to paid demand as the safe alternative.

`domain/golden_examples.yaml` records representative business questions and
their expected selections. These examples test interpretation only. Database
RLS, WAC privileges, query validation, and end-to-end generated SQL have their
own independent tests.
