# Pharma NL-to-SQL Assistant

An end-to-end conversational analytics application that turns business questions into safe SQL over a synthetic pharmaceutical sales dataset. The system combines domain-aware planning with deterministic SQL validation and database-enforced access control.

This repository has an independent Git history. The original assignment is used only as a source reference: [cveeraiy/nl2sql-assignment](https://github.com/cveeraiy/nl2sql-assignment).

## Architecture at a glance

- React and TypeScript chat interface
- Python and FastAPI backend
- PostgreSQL locally and Amazon RDS for PostgreSQL in AWS
- Database row-level security for territory and region scope
- Separate database privileges for WAC-sensitive queries
- Code-orchestrated LLM workflow with structured planning and SQL generation
- Deterministic validation with `sqlglot` before any query executes
- Terraform-managed EC2, RDS, S3, secrets, logging, and security groups

The complete decisions, assumptions, and trade-offs are in [DESIGN.md](DESIGN.md). The implementation sequence and quality gates are in [docs/implementation_plan.md](docs/implementation_plan.md).

## Local database quick start

Requirements: Docker with Compose.

```bash
cp .env.example .env
docker compose up -d --wait
./scripts/db_smoke_test.sh
```

The PostgreSQL container applies `schema/migrations/001_initial.sql` and then loads the supplied small fixture from `schema/seed_data.sql` when its data volume is first created.

Stop the database without deleting its data:

```bash
docker compose down
```

## Current status

Phase 1 — local PostgreSQL schema and fixture loading.

## Source material

- `docs/`: supplied pharmaceutical business rules and security model
- `schema/generate_data.py`: deterministic synthetic-data generator
- `schema/seed_data.sql`: small development fixture
- `schema/create_tables.sql`: supplied SQLite schema, retained as reference until the PostgreSQL migrations are added

Generated CSV files are intentionally excluded from Git.
