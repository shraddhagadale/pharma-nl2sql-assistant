# Architecture

## Trust boundaries

```text
Browser
  |  session cookie + natural-language question
  v
FastAPI boundary
  |-- resolves user identity and server-side role
  |-- supplies role-safe schema and bounded conversation
  v
LLM boundary
  |-- searches authoritative Markdown through local tools
  |-- returns a grounded decision and candidate SQL
  |-- has no database credentials or network path to PostgreSQL
  v
Deterministic SQL boundary
  |-- parses AST
  |-- enforces read-only and allowlist policies
  |-- selects limited or executive connection pool
  v
PostgreSQL boundary
  |-- applies transaction-local user context
  |-- enforces RLS on rows
  |-- enforces grants on WAC
  v
Bounded rows -> summarizer -> browser
```

The browser, the natural-language input, and every LLM output are untrusted. The backend is responsible for converting those inputs into a constrained operation. PostgreSQL is the final authority for row and column access.

## Component responsibilities

| Component | Responsibility | Explicitly does not do |
|---|---|---|
| React UI | Demo login, chat input, loading state, answer/table rendering, assumption and error display | Decide access scope or execute SQL |
| FastAPI routes | Validate API shape, resolve session, invoke workflow, shape response | Trust role fields from the browser |
| User-context service | Load role/territory/region/WAC flags from PostgreSQL | Infer permissions from natural language |
| Domain knowledge service | Search/read approved Markdown sections with provenance | Access the web, database, or arbitrary files |
| Planner | Resolve conversation context, retrieve domain evidence, and return a typed decision or analytics plan | Authorize database access or execute SQL |
| SQL generator | Produce PostgreSQL SQL from the approved plan and role-safe context | Execute SQL |
| SQL validator | Parse and enforce statement, relation, column, function, row-limit, and role rules | Replace database RLS |
| Query executor | Set transaction-local identity, select DB pool, apply timeout, return bounded rows | Repair or reinterpret SQL |
| PostgreSQL | Store analytics data and enforce row/column permissions | Decide conversational intent |
| Summarizer | Turn bounded rows and approved assumptions into a readable answer | Receive DB credentials or expand query scope |
| Audit service | Record decision/outcome metadata and timings | Store secrets or unrestricted query results |

## Agent state machine

```mermaid
stateDiagram-v2
    [*] --> ResolveUser
    ResolveUser --> SearchDocuments
    SearchDocuments --> ReadSection: more context needed
    ReadSection --> SearchDocuments
    SearchDocuments --> BuildPlan
    BuildPlan --> Denied: unavailable to authenticated role
    BuildPlan --> Clarification: unresolved material ambiguity
    BuildPlan --> GenerateSQL
    GenerateSQL --> ValidateSQL
    ValidateSQL --> RepairSQL: repairable validation error
    RepairSQL --> ValidateSQL
    ValidateSQL --> Rejected: unsafe or retry exhausted
    ValidateSQL --> ExecuteSQL: valid
    ExecuteSQL --> Summarize
    Summarize --> [*]
    Denied --> [*]
    Clarification --> [*]
    Rejected --> [*]
```

Repairs are bounded to a small fixed count. Each repair receives validator errors but never receives broader privileges. A request that cannot be made safe returns a useful failure message.

## Planned repository layout

```text
backend/
  app/
    api/              HTTP routes and dependencies
    agent/            workflow, prompts, and typed plans
    domain/           Markdown parsing and bounded knowledge tools
    security/         user context and policy decisions
    sql/              validator and executor
    db/               engine/session configuration
  tests/
frontend/
  src/
infra/
  terraform/
schema/
  migrations/         PostgreSQL migrations
  generated/          ignored CSV build artifacts
scripts/
docs/
```

## Database identity model

Application identity and database login identity are separate:

- The application session identifies a row in `users`.
- A narrowly scoped authentication pool can read only the approved user-context columns.
- The backend selects either the limited or executive database pool using that database-backed user record.
- The transaction sets `app.user_id` locally.
- RLS resolves scope from `users` and `zip_territory`.
- Column grants on the selected database role determine whether `wac` is even addressable.

Migrations and data loading use a separate administrative role that is never available to the request-serving process.

All three runtime login roles use `NOINHERIT` and have no direct table grants.
They can assume exactly one non-login group role: authentication, limited, or
executive. Transactions are read-only and apply a local statement timeout before
executing application SQL.

## Deployment topology

```mermaid
flowchart TB
    Internet -->|HTTP health check; HTTPS in application deployment| EC2[EC2: containerized web application]
    EC2 -->|5432, EC2 security group only| RDS[(RDS PostgreSQL, non-public)]
    EC2 --> S3[S3 data staging]
    EC2 --> Secrets[Secrets Manager or SSM]
    EC2 --> Logs[CloudWatch]
    TF[Terraform] --> EC2
    TF --> RDS
    TF --> S3
    TF --> Secrets
    TF --> Logs
```

V1 uses the default VPC and does not provision a custom VPC, NAT gateway, or VPC endpoints. That trade-off is detailed in `DESIGN.md`.
