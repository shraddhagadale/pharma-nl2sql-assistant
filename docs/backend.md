# Backend foundation

Phase 5 established the deterministic FastAPI security boundary. Phase 7 adds
the structured NL-to-SQL workflow without changing which component authorizes
or executes database access.

## Runtime identities

Application identity and PostgreSQL login identity remain separate:

| Login role | Assumable group role | Purpose |
| --- | --- | --- |
| `pharma_runtime_auth` | `pharma_app_auth` | Read the approved demo-user columns |
| `pharma_runtime_limited` | `pharma_app_limited` | Serve RAM and director analytics without WAC |
| `pharma_runtime_exec` | `pharma_app_exec` | Serve executive analytics including WAC |

Runtime logins have `NOINHERIT`, no direct table grants, and no membership in
each other's group roles. Every application transaction is read-only, applies a
statement timeout, assumes one fixed group role, and sets `app.user_id` with
transaction-local scope. The selected demo user is reloaded from PostgreSQL on
every authenticated request; the browser never supplies an authoritative role,
region, territory, or WAC flag.

## Routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process liveness |
| `GET` | `/ready` | Connectivity and role readiness for all three pools |
| `GET` | `/api/v1/demo/users` | List database-backed demo users |
| `POST` | `/api/v1/demo/session` | Select a user by `user_id` and create a signed session |
| `GET` | `/api/v1/demo/session` | Resolve the current session from PostgreSQL |
| `DELETE` | `/api/v1/demo/session` | Clear the current session |
| `GET` | `/api/v1/analytics/overview?months=3` | Run one predefined scoped analytic |
| `POST` | `/api/v1/chat` | Plan, validate, execute, and summarize a conversational analytic |

The overview endpoint uses a static, parameterized query. Limited roles never
address `sales.wac`; only the executive query contains the revenue expression.
The assumptions returned by the endpoint state the distributor, branded-product,
and period-offset defaults explicitly.

The chat endpoint uses the same database-backed session and pools. Its generated
SQL must pass the deterministic AST and domain-rule validator before the
executor sees it. See [agent.md](agent.md) for the workflow, configuration, and
safe-failure behavior.

## Local setup

Start PostgreSQL, prepare runtime roles for an existing database volume, then
start the application profile:

```bash
docker compose up -d --wait postgres
./scripts/setup_backend_db.sh
docker compose --profile application up -d --build --wait backend
```

A new PostgreSQL volume applies migrations `001` through `005` and the local
runtime-login initialization automatically. `setup_backend_db.sh` remains safe
to run for existing volumes and after local passwords change.

Run the tests and lint checks:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'
cd backend
.venv/bin/ruff check app tests
.venv/bin/ruff format --check app tests
.venv/bin/python -m pytest
```

The integration suite requires the local PostgreSQL container on port `5433`.

Run the same HTTP-level session, RLS-scope, and revenue-visibility assertions
used by AWS Checkpoint 3 with:

```bash
./scripts/backend_api_smoke_test.py http://localhost:8000
```

The EC2-only `scripts/aws_backend_checkpoint_remote.sh` runner is intentionally
ephemeral: it applies the idempotent runtime-access migration, generates
one-run credentials on the instance, runs the backend against private RDS, and
then removes the container and image and restores all runtime accounts to
`NOLOGIN`. It is a checkpoint tool, not the Phase 9 deployment mechanism.

## Audit foundation

Session and analytics operations emit structured JSON with request ID, user ID,
database-backed role, action, outcome, duration, row count, and a bounded error
code. Audit events intentionally omit cookies, passwords, SQL parameters, and
query result values. The existing CloudWatch agent can collect the same events
when the application is deployed in a later phase.
