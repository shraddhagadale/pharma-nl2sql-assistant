# Evaluation and Final Evidence

Date verified: 2026-09-25

## Evaluation model

The project separates reproducible safety/correctness evaluation from live LLM
behavior:

1. **Deterministic evaluation** checks Markdown knowledge loading/search, SQL
   structure, role-visible columns, parameterization, and result bounds. It
   requires no external model and must pass on every change.
2. **Integration evaluation** exercises the actual FastAPI workflow, SQL
   validator, role-specific connection pools, PostgreSQL RLS/grants, and React
   proxy boundary with injected typed planner results.
3. **Conversation-quality evaluation** uses generic identities and locations to
   test clarification, access limits, no-data handling, timeout/failure language,
   and the removal of implementation terminology from user-facing answers.
4. **Live conversation evaluation** calls the configured remote model through
   the deployed product. It is a configuration-dependent release gate and is
   never replaced by a scripted model while being reported as live.

## Versioned deterministic suite

Run:

```bash
backend/.venv/bin/python scripts/run_evaluation.py
backend/.venv/bin/python scripts/run_evaluation.py --json
```

Current result: **11/11 SQL-policy cases passed**.

| Suite | Cases | Coverage |
| --- | ---: | --- |
| SQL policy | 11 | Stacked statements, system catalogs, file access, comments, star selection, nested WAC, literal injection, cross joins, row limits, executive revenue, and named parameters |

The source cases are versioned in `evaluation/sql_policy_cases.json`.
`backend/tests/test_evaluation_suite.py` makes the suite part of the normal test
run. `backend/tests/test_domain_knowledge.py` independently verifies the approved
document set, retrieval, exact-section reads, digests, and path boundaries.

## Regression evidence

- Backend: **52 tests passed**, including real local PostgreSQL product-flow
  tests across RAM, director, and executive identities plus generalized
  conversation-outcome and geography-scope coverage.
- Frontend: type checking and linting passed; **3 component tests passed**; the
  production Vite build passed.
- Local containers: database fixture, RLS/WAC security, same-origin frontend,
  CSP headers, sessions, and access-limited response smoke tests passed.
- Terraform: formatting, validation, and the mocked security test passed; the
  live stack reported **no drift** after deployment.
- Cloud full data: exact counts and checksums passed for 40,000 organizations,
  40 products, 29,728 ZIP mappings, 2,000,000 sales, and 23 users.
- Cloud RLS/WAC API: RAM `U009` saw 1,706 organizations, Northeast director
  `U003` saw 3,304, and executive `U001` saw 25,561 for the same three-month
  overview. Revenue was hidden for limited roles and present for the executive.

## Live cloud conversation gate

With `openai_api_key` configured in the application-runtime secret and the
application deployed, run:

```bash
python3 scripts/cloud_conversation_smoke_test.py http://100.28.234.67
```

The script verifies:

- RAM revenue denial without allowing WAC SQL to execute;
- RAM paid demand;
- director top-10 accounts;
- a bounded marker-free multi-turn period follow-up with SQL semantics checked;
- executive gross revenue; and
- product-specific market share with safe zero-denominator handling.

The gate passed against the AWS deployment on 2026-09-25. The marker-free
follow-up replaced the prior rolling-three-month result with the most recently
completed full month and produced an equality predicate on `mo_offset`. During
the gate, underspecified top-account and market-share questions correctly
returned business-language clarifications instead of inventing missing scope.

## Known limitations

- The public demo is HTTP-only because no domain/certificate was supplied. Use
  only the synthetic assignment data.
- Demo user selection is not production authentication.
- The generated `market_data` rows are all competitors, so the synthetic
  denominator does not demonstrate branded rows in that source. Domain-formula
  accuracy is evaluated through grounded live-agent cases rather than duplicated
  validator rules.
- Model quality, retrieval relevance, latency, and repair rate require continued
  live measurement. The deterministic validator and database controls do not
  depend on that outcome.
