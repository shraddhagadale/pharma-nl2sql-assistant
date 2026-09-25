# Pharma NL-to-SQL Assistant

An end-to-end conversational analytics application that turns business questions into safe SQL over a synthetic pharmaceutical sales dataset. The system combines domain-aware planning with deterministic SQL validation and database-enforced access control.

This repository has an independent Git history. The original assignment is used only as a source reference: [cveeraiy/nl2sql-assignment](https://github.com/cveeraiy/nl2sql-assignment).

## Submission links

| Deliverable | Link |
| --- | --- |
| Live application | [http://100.28.234.67](http://100.28.234.67) |
| Architecture, assumptions, and decisions | [DESIGN.md](DESIGN.md) |
| Test cases and recorded results | [docs/test_results.md](docs/test_results.md) |
| Evaluation methodology | [docs/evaluation.md](docs/evaluation.md) |
| AWS deployment and rollback | [docs/deployment.md](docs/deployment.md) |
| Verified application release | [`5909c86`](https://github.com/shraddhagadale/pharma-nl2sql-assistant/commit/5909c8676891672930c371fde81832f430663cb4) |
| Successful CI and deployment evidence | [GitHub Actions run 36181367805](https://github.com/shraddhagadale/pharma-nl2sql-assistant/actions/runs/36181367805) |

The public endpoint is intentionally HTTP-only because the synthetic-data demo
has no domain or trusted certificate. Do not submit real patient, prescriber,
facility, or other sensitive information.

## Architecture at a glance

- React and TypeScript chat interface served through an Nginx same-origin proxy
- Python and FastAPI backend
- PostgreSQL locally and Amazon RDS for PostgreSQL in AWS
- Database row-level security for territory and region scope
- Separate database privileges for WAC-sensitive queries
- Code-orchestrated LLM workflow with structured planning and SQL generation
- Deterministic validation with `sqlglot` before any query executes
- Terraform-managed EC2, RDS, S3, secrets, logging, and security groups

The final architecture, prompt/security boundaries, assumptions, implementation
decisions, performance rationale, and trade-offs are in [DESIGN.md](DESIGN.md).
The implementation sequence and quality gates are in
[docs/implementation_plan.md](docs/implementation_plan.md).

## Local database quick start

Requirements: Docker with Compose.

```bash
cp .env.example .env
docker compose up -d --wait
./scripts/db_smoke_test.sh
```

The PostgreSQL container applies `schema/migrations/001_initial.sql` and then loads the supplied small fixture from `schema/seed_data.sql` when its data volume is first created.

Run both database checks:

```bash
./scripts/db_smoke_test.sh
./scripts/security_smoke_test.sh
```

Apply a new migration to an existing local volume with:

```bash
./scripts/apply_local_migration.sh schema/migrations/003_security.sql
```

Stop the database without deleting its data:

```bash
docker compose down
```

## Backend quick start

The FastAPI backend provides database-backed demo sessions, role-scoped
connection pools, a predefined safe analytics endpoint, and the structured
NL-to-SQL workflow. Copy `.env.example` to `.env` and set
`PHARMA_OPENAI_API_KEY` to enable model-backed chat.

```bash
docker compose up -d --wait postgres
./scripts/setup_backend_db.sh
docker compose --profile application up -d --build --wait
curl http://localhost:8000/ready
```

The application is available at `http://localhost:3000`. The API remains
available at `http://localhost:8000`, with interactive documentation at
`http://localhost:8000/docs`. See [docs/backend.md](docs/backend.md) for its
routes and [docs/frontend.md](docs/frontend.md) for the UI workflow and tests.

The conversational route is `POST /api/v1/chat`. Its model, validator, repair,
execution, and fallback boundaries are documented in [docs/agent.md](docs/agent.md).

## Evaluation

The submission-facing expected-versus-actual evidence is in
[docs/test_results.md](docs/test_results.md). It consolidates the versioned SQL
policy cases, representative generated SQL, role-scope results, edge cases,
full-data checks, performance evidence, and the existing successful cloud gate.

Run the versioned SQL security-policy suite with:

```bash
backend/.venv/bin/python scripts/run_evaluation.py
```

The suite covers dangerous SQL, WAC boundaries, parameterization, and row
limits. Domain interpretation and multi-turn behavior are evaluated separately
through Markdown retrieval tests and the live model gate documented in
[docs/evaluation.md](docs/evaluation.md).

## Domain knowledge

The supplied Markdown files are the runtime source of pharmaceutical business
knowledge. The agent searches and reads their sections through bounded local
tools before producing an analytics plan; there is no duplicated YAML catalog.
Run the retrieval tests with:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_domain_knowledge.py
```

See [docs/domain_knowledge.md](docs/domain_knowledge.md) for document scope,
search behavior, tool contracts, and update workflow.

## Full synthetic dataset

Generate and load the full dataset into a separate `pharma_full` database:

```bash
python3 schema/generate_data.py
./scripts/load_full_data.sh
./scripts/full_data_quality.sh
POSTGRES_DB=pharma_full ./scripts/security_smoke_test.sh
./scripts/performance_smoke_test.sh
```

The generated CSVs are ignored by Git. The loader refuses to write into an already initialized target database; choose another `FULL_POSTGRES_DB` name when a clean reload is required.

## AWS infrastructure

Terraform for the demo AWS foundation is under `infra/terraform`. It provisions EC2, non-public RDS PostgreSQL, private S3 staging, an RDS-managed Secrets Manager credential, CloudWatch logs, Systems Manager access, IAM, and security groups in the account's default VPC.

See `infra/terraform/README.md` for review, cost, plan, apply, verification, and teardown instructions. Running Terraform locally does not happen automatically and no AWS resources are created merely by cloning this repository.

The deployed synthetic-data demo is available at
[http://100.28.234.67](http://100.28.234.67). It is intentionally HTTP-only;
see [docs/deployment.md](docs/deployment.md) for the release workflow, security
boundaries, live evidence, cost warning, and model-secret limitation.

Pull requests run the complete application and infrastructure verification
suite. Successful commits to `main` are deployed automatically to the AWS demo
through a short-lived, environment-scoped GitHub OIDC role; application runtime
secrets remain in AWS Secrets Manager.

## Current status

Phase 10 implementation and deployment automation are complete. The public
application runs against the complete RDS dataset and the remote model is
configured. The direct Markdown knowledge-tool architecture and marker-free
conversation follow-ups passed the recorded live cloud conversation gate for
application commit `5909c86`. Final documentation changes do not alter or
redeploy that verified application release.

Known limitations include demo-user selection rather than production identity,
HTTP-only transport, a single EC2 application host, local Terraform state, and
the supplied synthetic `market_data` composition. These assumptions and their
production alternatives are documented explicitly in [DESIGN.md](DESIGN.md).

## Source material

- `docs/`: supplied pharmaceutical business rules and security model
- `schema/generate_data.py`: deterministic synthetic-data generator
- `schema/seed_data.sql`: small development fixture
- `schema/create_tables.sql`: supplied SQLite schema retained as source reference alongside the PostgreSQL migrations

Generated CSV files are intentionally excluded from Git.
