# Structured NL-to-SQL agent

Phase 7 adds an application-owned, explicit Python workflow. The model is a
planner and summarizer; it is not given database credentials, a database tool,
or authority to decide access. FastAPI owns the workflow and every security
decision after model output.

## Request contract

`POST /api/v1/chat` requires the signed demo session created by
`POST /api/v1/demo/session`.

```json
{
  "question": "Show paid demand for Zenovax over the last 3 months",
  "conversation": [],
  "include_sql": false
}
```

The optional conversation is limited to twelve turns of 1,000 characters each;
the current question is limited to 2,000 characters. SQL is omitted unless the
caller intentionally sets `include_sql` to `true`.

Responses use explicit application statuses so the UI never has to infer an
outcome from technical text:

- `answered`: the requested business result is available
- `clarification`: a material ambiguity must be resolved before execution
- `no_data`: execution succeeded but no meaningful value was available in scope
- `denied`: the grounded planner identified data unavailable to the authenticated role
- `error`: execution timed out or failed after validation
- `rejected`: generated SQL did not pass validation

If no model key is configured, the backend remains healthy but this route
returns HTTP 503. This keeps database, session, and readiness checks usable
without pretending that NL-to-SQL inference is available.

## Workflow and trust boundaries

1. The signed session resolves a fresh user, role, region, territory, and WAC
   flag from PostgreSQL.
2. The backend supplies the bounded conversation, database-backed user context,
   and role-safe schema to the planning model. A role claimed in chat is never
   authoritative.
3. The backend deterministically prefetches the four best-matching Markdown
   sections before the first model call. The model may call
   `search_domain_knowledge` or `read_domain_section` when those sections are
   insufficient. Both tools read only the approved local Markdown corpus.
4. The model resolves short follow-ups into a standalone business question,
   including follow-ups to a timed-out request, and grounds its interpretation in
   the retrieved sections.
5. The model returns a Pydantic `AnalyticsPlan` with a query, clarification, or
   denied decision. Query plans include the resolved question, document evidence,
   business labels, assumptions, optional geography, named parameters, and one
   candidate PostgreSQL query.
6. Code classifies ambiguous city references and compares explicit city/state,
   ZIP, territory, and region references with the user's assigned scope before
   analytics execution. PostgreSQL RLS remains the final boundary if a reference
   is absent or misclassified.
7. `sqlglot` parses the SQL. Deterministic checks allow only one bounded read-only
   query over the approved role-safe schema. The validator does not reinterpret
   the document-grounded business request.
8. One repair attempt is allowed by default. The model receives validator
   issues and may consult the Markdown tools again, but it cannot change the
   authenticated role or broaden geographic scope. A second invalid result fails
   closed.
9. The executor chooses the limited or executive pool from the database-backed
   user, starts a read-only transaction, sets `app.user_id` locally, and runs
   only the validated parameterized SQL.
10. PostgreSQL RLS restricts rows and database grants independently restrict WAC.
11. Code classifies empty results, null-only aggregates, timeouts, and other
    execution failures into distinct outcomes with business-language messages.
12. The model summarizes only a bounded meaningful result. A language guard
    replaces technical summaries, and a deterministic conversational fallback
    keeps the result table available if summarization fails.
13. The complete request has a 42-second application deadline inside the
    55-second proxy deadline. Summarization has its own six-second budget and
    falls back without discarding validated results.
14. Because analytics chat requests are read-only and idempotent, the web client
    retries one transient 502, 503, or 504 response with the exact same payload.
    If both attempts fail, it shows business-safe language and an explicit retry
    control; failure text is never added to conversation context.

The model never receives a generic database execution tool. This avoids a path
where prompt text could bypass validation or where model-selected credentials
could broaden access.

## Model integration

The default provider uses the OpenAI Responses API through backend Python code.
Planning uses a bounded Responses API function-calling loop followed by Pydantic
Structured Outputs. Repair uses the same document tools, while summarization
uses Structured Outputs without tools. The
default model is `gpt-5.6-sol`, configurable through
`PHARMA_OPENAI_MODEL`. Its reasoning effort defaults to `medium` and is
configurable through `PHARMA_OPENAI_REASONING_EFFORT`. The provider can be
replaced through the internal `PlanningModel` protocol without changing policy,
validation, or execution.

Configuration:

```dotenv
PHARMA_OPENAI_API_KEY=
PHARMA_OPENAI_MODEL=gpt-5.6-sol
PHARMA_OPENAI_REASONING_EFFORT=medium
PHARMA_OPENAI_REQUEST_TIMEOUT_SECONDS=20
PHARMA_AGENT_REQUEST_TIMEOUT_SECONDS=42
PHARMA_AGENT_SUMMARY_TIMEOUT_SECONDS=6
PHARMA_AGENT_MAX_REPAIRS=1
PHARMA_AGENT_MAX_ROWS=100
```

The key is server-only and must not be committed or sent by a browser. The
implementation follows the OpenAI
[Function calling guide](https://developers.openai.com/api/docs/guides/function-calling),
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
and uses a model that supports the Responses API and Structured Outputs, as
listed on the [GPT-5.6 Sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol).

## Deterministic SQL policy

The validator enforces:

- exactly one PostgreSQL `SELECT`, with bounded joins, CTEs, and subqueries
- approved tables, role-visible columns, and approved functions only
- no schema qualification, comments, `SELECT *`, DDL, DML, transaction control,
  locks, grants, external access, or system/user tables
- exact agreement between typed plan parameters and SQL placeholders
- named parameters for user-derived string values
- forced or clamped outer `LIMIT`
- WAC rejection for every non-executive SQL expression

The validator returns normalized SQL, bound values, referenced objects, the row
limit, and a SHA-256 SQL fingerprint. Audit logs contain the fingerprint and
outcome, not raw prompts, SQL parameter values, credentials, or result rows.
Market-share plans must also contain an explicit product or therapeutic-market
filter, or group by a product/market dimension. Otherwise the workflow requests
clarification before execution rather than combining unrelated markets.

## Local verification

Install dependencies and run all tests with PostgreSQL listening on port 5433:

```bash
backend/.venv/bin/pip install -e 'backend[dev]'
cd backend
.venv/bin/ruff check app tests
.venv/bin/ruff format --check app tests
.venv/bin/python -m pytest
```

The tests use injected fake planning models, so they verify the complete
planning-validation-execution-response path without spending API tokens or
depending on a remote model. Separate tests verify Markdown loading, ranking,
exact-section reads, tool boundaries, and citation handoff. A live conversational
smoke test additionally requires `PHARMA_OPENAI_API_KEY`.

The conversation-quality suite uses generic users and locations rather than
hard-coding one demo identity. It covers ambiguous geography, cross-scope
requests, null-only aggregates, timeouts, other execution failures, and removal
of technical language from answers and notes.
