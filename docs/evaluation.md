# Evaluation and Final Evidence

Date verified: 2026-09-24

## Evaluation model

The project separates reproducible safety/correctness evaluation from live LLM
behavior:

1. **Deterministic evaluation** checks business-language selection, role policy,
   SQL structure, business predicates, parameterization, and result bounds. It
   requires no external model and must pass on every change.
2. **Integration evaluation** exercises the actual FastAPI workflow, SQL
   validator, role-specific connection pools, PostgreSQL RLS/grants, and React
   proxy boundary with injected typed planner results.
3. **Live conversation evaluation** calls the configured remote model through
   the deployed product. It is a configuration-dependent release gate and is
   never replaced by a scripted model while being reported as live.

## Versioned deterministic suite

Run:

```bash
backend/.venv/bin/python scripts/run_evaluation.py
backend/.venv/bin/python scripts/run_evaluation.py --json
```

Current result: **24/24 passed**.

| Suite | Cases | Coverage |
| --- | ---: | --- |
| Golden selection | 8 | Metrics, periods, dimensions, sources, defaults, comparison, and role denial |
| Adversarial selection | 4 | Prompt override, role spoofing, hidden pricing intent, and unknown-request defaults |
| SQL policy | 12 | Stacked statements, system catalogs, file access, comments, star selection, nested WAC, wrong periods, literal injection, cross joins, row limits, executive revenue, and named parameters |

The source cases are versioned in `domain/golden_examples.yaml` and
`evaluation/adversarial_cases.yaml`. `backend/tests/test_evaluation_suite.py`
makes the complete suite part of the normal test run.

## Regression evidence

- Backend: **52 tests passed**, including real local PostgreSQL product-flow
  tests across RAM, director, and executive identities.
- Frontend: type checking and linting passed; **3 component tests passed**; the
  production Vite build passed.
- Local containers: database fixture, RLS/WAC security, same-origin frontend,
  CSP headers, sessions, and pre-model denial smoke tests passed.
- Terraform: formatting, validation, and the mocked security test passed; the
  live stack reported **no drift** after deployment.
- Cloud full data: exact counts and checksums passed for 40,000 organizations,
  40 products, 29,728 ZIP mappings, 2,000,000 sales, and 23 users.
- Cloud RLS/WAC API: RAM `U009` saw 1,706 organizations, Northeast director
  `U003` saw 3,304, and executive `U001` saw 25,561 for the same three-month
  overview. Revenue was hidden for limited roles and present for the executive.

## Live cloud conversation gate

After `openai_api_key` is securely added to the application-runtime secret and
the application is redeployed, run:

```bash
python3 scripts/cloud_conversation_smoke_test.py http://100.28.234.67
```

The script verifies:

- RAM revenue denial before model execution;
- RAM paid demand;
- director top accounts;
- a bounded multi-turn period follow-up;
- executive gross revenue; and
- market share with safe zero-denominator handling.

Current result: **not run to completion because no OpenAI API key is
configured**. The deployed backend returns the intended safe HTTP 503 on the
first model-dependent case. This is an external configuration gap, not a
reported pass.

## Known limitations

- The public demo is HTTP-only because no domain/certificate was supplied. Use
  only the synthetic assignment data.
- Demo user selection is not production authentication.
- The generated `market_data` rows are all competitors, so the synthetic
  denominator does not demonstrate branded rows in that source even though the
  documented formula is enforced.
- Model quality, latency, and repair rate still need live measurements once the
  runtime key is configured. The deterministic validator and database controls
  do not depend on that outcome.
