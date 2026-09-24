# AWS Checkpoint 2 — Infrastructure and Database

Date verified: 2026-09-24  
Region: `us-east-1`

## Outcome

The Terraform demo stack was applied successfully from the reviewed saved plan:

- 22 resources added
- 0 resources changed
- 0 resources destroyed
- final drift check: no changes

The deployed resources are intentionally small and disposable, but they are
billable while running.

## Infrastructure verification

- EC2 is reachable on the temporary HTTP `/health` endpoint and returns `ok`.
- EC2 is registered and online in AWS Systems Manager; there is no inbound SSH
  rule.
- RDS runs PostgreSQL 16, is encrypted, is not publicly accessible, and accepts
  port 5432 only from the EC2 application security group.
- The application security group exposes only the temporary port 80 demo
  endpoint and allows outbound traffic required for packages, AWS APIs, and
  model APIs.
- The S3 staging bucket blocks public access, enforces TLS, enables server-side
  encryption and versioning, and expires incomplete/noncurrent data according
  to its lifecycle policy.
- CloudWatch receives the EC2 bootstrap and application log streams.
- The RDS master credential is generated and managed by RDS in Secrets Manager;
  no database password is stored in Git or Terraform variables.

## Database verification

Migrations were executed from EC2 through Systems Manager. EC2 retrieved the
SQL files from the private S3 bucket and connected to RDS with TLS, keeping the
database private from the development laptop.

Small-fixture counts:

| Table | Rows |
| --- | ---: |
| `organizations` | 85 |
| `products` | 40 |
| `zip_territory` | 116 |
| `sales` | 271 |
| `users` | 23 |

Security assertions passed in RDS:

- RAM `U009` sees only `New York Metro`.
- Director `U003` sees only the `Northeast` region.
- Executive `U001` sees all 85 fixture organizations through the executive
  database role.
- An executive identity used through the limited pool sees zero rows.
- An unknown identity sees zero rows.
- The limited role cannot select `sales.wac`; the executive role can.
- `organizations` and `sales` both have enabled and forced RLS.
- Neither application database role has `SUPERUSER` or `BYPASSRLS`.

## RDS portability fix

The initial security migration attempted to explicitly set `NOSUPERUSER` and
`NOBYPASSRLS`. Amazon RDS master users have `rds_superuser`, not PostgreSQL's
true `SUPERUSER`, so RDS correctly rejected changing the `SUPERUSER` bit.

The migration now:

1. creates the application roles with PostgreSQL's safe defaults;
2. alters only attributes the RDS administrator is allowed to manage; and
3. fails closed if either existing application role has `SUPERUSER` or
   `BYPASSRLS`.

The revised migration and RLS optimization were re-applied locally to both the
small fixture and the 2-million-row database. Both security smoke suites passed
before the migration was retried successfully in RDS.

## Operational notes

- Terraform state and browser-authenticated AWS session files are local and
  ignored by Git. Remote state bootstrap remains a future hardening task.
- The one-time bootstrap used a browser-authenticated root session because the
  account did not yet expose an IAM Identity Center or administrator-role
  profile. Further AWS work should use a named administrator role or IAM
  Identity Center instead of the root identity.
- The temporary endpoint is HTTP for the infrastructure checkpoint only. The
  final application deployment must add trusted HTTPS before it is presented as
  production-like.
- RDS deletion protection and final snapshots are disabled for this disposable
  demo. Run `terraform destroy` when the environment is no longer needed to stop
  ongoing charges.
