# AWS Checkpoint 3 — Secure Backend

Date verified: 2026-09-24
Region: `us-east-1`

## Outcome

Checkpoint 3 passed locally and against the small fixture in private Amazon RDS.
The test exercised the Phase 5 FastAPI service through its HTTP API rather than
querying PostgreSQL directly.

The permanent application deployment remains Phase 9. For this checkpoint, EC2
built and ran a temporary backend container on its host network, accessed it
only through `127.0.0.1:8000`, and removed it after verification. The public
port-80 endpoint still serves only the infrastructure health page.

## Local verification

- PostgreSQL and the backend containers were healthy.
- `/ready` confirmed all three role-specific connection pools.
- The backend test suite passed: 19 tests.
- The database fixture and RLS/WAC smoke suites passed.
- `scripts/backend_api_smoke_test.py` passed against `localhost:8000`.
- The domain knowledge, lint, and formatting checks passed. The current
  architecture reads the authoritative Markdown documents directly.

The API smoke test verified anonymous denial, unknown-user denial, rejection of
a client-supplied role, database-backed sessions, RLS-visible analytics, and
role-appropriate revenue output.

## AWS verification

Before the application test:

- EC2 was running and online in Systems Manager.
- RDS PostgreSQL 16.13 was available, encrypted, and not publicly accessible.
- the existing temporary Nginx `/health` endpoint returned `ok`.

The EC2-to-RDS application run then produced these three-month paid-demand
results from the small fixture:

| User | Role and scope | Visible organizations | Revenue response |
| --- | --- | ---: | --- |
| `U009` | RAM, New York Metro | 3 | Hidden / `null` |
| `U003` | Director, Northeast | 6 | Hidden / `null` |
| `U001` | Executive, global | 33 | Visible |

These are organizations with matching distributor transactions in the selected
three-month window, not the total organization rows visible to each role.

The successful Systems Manager execution was
`6157ed6e-7fd4-46b0-87fb-5c49c14d988c`.

## Integration findings

The checkpoint caught three deployment-boundary assumptions before the agent
phase:

1. The base EC2 bootstrap did not install the PostgreSQL client. The repeatable
   checkpoint runner now installs `postgresql16` when `psql` is absent.
2. RDS had the Phase 2 RLS migrations but not the Phase 5 runtime-access
   migration. The runner now applies idempotent migration
   `005_runtime_access.sql` before starting the backend.
3. Amazon Linux's system Python is older than the backend container's Python.
   The standalone standard-library smoke client now postpones annotation
   evaluation and works in both environments.

## Credential and cleanup behavior

The runner retrieves the RDS-managed master credential on EC2, generates
one-run random runtime passwords and a session secret, and never sends those
values from the development machine. Runtime login roles are enabled only for
the test duration.

After the successful run:

- the temporary backend container was removed;
- `pharma_runtime_auth`, `pharma_runtime_limited`, and `pharma_runtime_exec`
  were all verified as `NOLOGIN`;
- port 8000 no longer served the backend;
- the temporary source bundle was deleted from S3; and
- the temporary backend image was removed from EC2.

The role/container cleanup verification execution was
`3d892ce1-98f7-4692-9563-b3b1700d2a57`; the image-removal verification was
`fb8394c8-4225-4c6f-ac44-062e947521b6`.

## Remaining boundary

This checkpoint does not claim a deployed conversational product. It validates
the secure backend and AWS-to-RDS path using predefined analytics. Phase 7 adds
the NL-to-SQL agent, Phase 8 adds the frontend, and Phase 9 performs the durable
deployment with runtime secret storage and trusted HTTPS.

The EC2, RDS, Elastic IP, storage, and logs remain live and billable until the
Terraform stack is destroyed.
