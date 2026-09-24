# Implementation Plan

The phase order is fixed. A checkpoint is a quality gate: failures are corrected in focused commits before work moves to the next dependent phase.

## Phase 0 — Project foundation

- Create the independent repository and source attribution.
- Document architecture, assumptions, security model, AWS trade-offs, and delivery cadence.
- Establish ignore rules for generated data, secrets, dependencies, and infrastructure state.

Commit: `docs: add architecture and implementation plan`

## Phase 1 — Local database setup

- Add Docker Compose PostgreSQL.
- Convert the supplied SQLite DDL to PostgreSQL migrations.
- Add a small fixture loader and seed users.
- Add baseline indexes.

Commit: `db: add local postgres schema and fixture loader`

## Phase 2 — RLS and security

- Add RLS policies for organizations and sales.
- Add executive and limited database roles.
- Enforce WAC column restrictions.
- Add local security integration tests.

Commit: `security: add rls policies and access-control tests`

## Checkpoint 1 — Local database security gate

Verify that RAMs see only their territory, directors see only their region, executives see all permitted data, non-executives cannot address WAC, and market data follows the same row scope.

## Phase 3 — Full data load and performance

- Add generated-CSV loaders.
- Load the complete local dataset.
- Add data-quality checks.
- Tune query indexes using representative analytics.

Commit: `data: add generated data loader and quality checks`

## Phase 4 — AWS infrastructure as code

- Add Terraform for EC2, RDS PostgreSQL, S3 staging, secret/config storage, CloudWatch, and security groups.
- Keep RDS non-public and restrict port 5432 to the EC2 security group.
- Record the no-custom-VPC demo trade-off.

Commit: `infra: add aws ec2 and rds infrastructure`

## Checkpoint 2 — Cloud infrastructure gate

Deploy the base infrastructure and verify EC2 reachability, RDS availability, EC2-to-RDS connectivity, secret/config wiring, and migration execution against RDS.

## Phase 5 — Backend without the agent

- Add FastAPI, health checks, and typed configuration.
- Add demo login/user selection and server-side user context.
- Set `app.user_id` within every query transaction.
- Add a predefined safe analytics endpoint and audit foundation.

Commit: `backend: add role-scoped query executor`

## Phase 6 — Deterministic domain layer

- Add `domain/domain_catalog.yaml` with source provenance.
- Add the catalog loader and validator.
- Add initial golden business examples.

Commit: `domain: add catalog-backed business rules`

## Checkpoint 3 — Secure backend gate

Test locally and against a small AWS fixture. Verify backend user context, API-visible RLS behavior, WAC/revenue denial, scoped predefined analytics, and AWS-to-RDS operation.

## Phase 7 — NL-to-SQL agent

- Add the structured analytics planner.
- Add role-safe schema and domain-rule context.
- Add SQL generation and `sqlglot` validation.
- Add bounded repair/safe-failure behavior.
- Add result summarization.

Commit: `agent: add structured nl-to-sql planner`

## Phase 8 — Frontend

- Add the React/TypeScript application.
- Add the demo user switcher and chat interface.
- Render answers, tables, assumptions, and safe error messages.
- Make SQL visible only through an intentional diagnostic affordance.

Commit: `frontend: add analytics chat interface`

## Checkpoint 4 — Local product gate

Run the full application locally. Verify UI/API integration, valid scoped SQL, validator rejection, RLS, WAC denial, and representative demo questions.

## Phase 9 — AWS deployment

- Deploy the application on EC2.
- Run RDS migrations and full-data loading.
- Configure runtime secrets and environment.
- Add a public app URL and cloud smoke script/results.

Commit: `deploy: add aws deployment workflow and smoke results`

## Checkpoint 5 — Cloud product gate

Verify health, demo login, scoped conversations for all roles, WAC/revenue refusal, executive revenue, market share, top accounts, multi-turn follow-up, and validation failure behavior.

## Phase 10 — Evaluation and polish

- Add golden NL-to-SQL and security evaluation suites.
- Add prompt-injection and edge-case tests.
- Add `docs/evaluation.md`, `docs/deployment.md`, final README instructions, and demo script.

Commit: `eval: add final test suite and project evidence`

## Working cadence

For each phase:

1. Implement the smallest coherent slice.
2. Run local automated and manual checks.
3. Commit the phase or focused fix.
4. Deploy only at the scheduled integration checkpoint.
5. Record cloud-specific fixes separately.
