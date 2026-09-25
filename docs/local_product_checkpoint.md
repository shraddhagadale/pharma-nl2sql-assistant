# Checkpoint 4 — Local Product Gate

Date verified: 2026-09-24

## Outcome

The local product stack passes its deterministic integration gate. The React
application, Nginx same-origin proxy, FastAPI session/chat APIs, SQL validator,
role-selected database pools, and PostgreSQL RLS/WAC controls are exercised
together or at their closest test boundary.

No OpenAI key was present during this checkpoint. Model-dependent integration
tests therefore inject typed, deterministic planner outputs at the provider
boundary. They still use the real workflow, validator, SQL executor, database,
RLS policies, role grants, response schema, and session API. This verifies the
application-owned safety path without presenting a scripted model as a live
remote inference test.

## Verified behaviors

- The complete backend suite passes with 51 tests, and the frontend suite passes
  type checking, linting, 3 component tests, and a production build.
- RAM, director, and executive users receive strictly increasing paid-demand
  scope for the same validated SQL because PostgreSQL applies their territory,
  region, or global access.
- A RAM pricing question is denied before the planning model is called.
- An executive can execute a validated gross-revenue query containing WAC.
- A director can receive ranked grandparent-account results.
- A follow-up can inherit the paid-demand metric while explicitly comparing R3M
  and prior R3M using both documented predicates.
- The frontend renders the user scope, table results, assumptions, diagnostic
  SQL, and the safe model-unavailable state.
- The container endpoint supplies CSP and other security headers, proxies the
  signed session on one origin, and preserves the pre-model pricing denial.
- Database, security, and frontend smoke scripts pass against the rebuilt
  three-service Docker Compose stack.

## Commands

```bash
cd backend
.venv/bin/python -m pytest

cd ../frontend
npm run typecheck
npm run lint
npm run test:run
npm run build

cd ..
docker compose --profile application up -d --build --wait
./scripts/frontend_smoke_test.sh http://localhost:3000
./scripts/db_smoke_test.sh
./scripts/security_smoke_test.sh
```

## Remaining configuration-dependent check

A live remote-model conversation requires a server-side
`PHARMA_OPENAI_API_KEY`. That check will be performed during deployment when the
runtime secret is available. The application intentionally returns HTTP 503 for
ordinary analytics if the key is missing while keeping health, login, and
deterministic policy behavior operational.
