# AWS Deployment

Date verified: 2026-09-24  
Region: `us-east-1`  
Public demo: [http://100.28.234.67](http://100.28.234.67)

## Deployed topology

- Terraform-managed EC2 `t3.small` serves the React/Nginx frontend on port 80.
- FastAPI runs in a private Docker network and is reachable only through the
  same-origin Nginx proxy.
- RDS PostgreSQL 16.13 is non-public and accepts port 5432 only from the EC2
  security group.
- The generated CSVs are staged in a private, encrypted, versioned S3 bucket.
- The RDS-managed master secret is used only for migrations, data loading, and
  runtime-role password updates.
- A separate Terraform-managed Secrets Manager secret stores random runtime
  role passwords, the session secret, and an optional model API key. Terraform
  owns the secret metadata but does not place secret values in state.
- Systems Manager performs deployment; inbound SSH is not allowed.

The demo deliberately uses the default VPC and HTTP. This synthetic-data
assignment has no domain or certificate. A production deployment would add a
trusted HTTPS endpoint, managed identity, WAF/load balancer, private application
subnets, restricted egress, secret rotation, and high availability.

## Repeatable release

Generate the complete dataset before the first release, apply Terraform, then
run the deployment wrapper:

```bash
python3 schema/generate_data.py
./scripts/validate_infra.sh
cd infra/terraform
terraform plan -out=phase9.tfplan
terraform apply phase9.tfplan
cd ../..
./scripts/deploy_aws.sh
```

`deploy_aws.sh` packages tracked source, synchronizes the ignored generated
CSVs to S3, and invokes `aws_deploy_remote.sh` through Systems Manager. The
remote workflow:

1. verifies all four dataset SHA-256 hashes;
2. loads the full dataset transactionally when exact counts are absent;
3. reapplies RLS, grants, and runtime-access migrations;
4. verifies 40,000 organizations, 40 products, 29,728 ZIP mappings, 2,000,000
   sales rows, and 23 users;
5. creates or reuses runtime credentials in Secrets Manager;
6. builds the backend and frontend images;
7. starts restartable containers on a private Docker network; and
8. runs internal readiness plus public same-origin smoke tests.

The workflow is idempotent for the current dataset version: later releases
reuse S3 objects, skip a matching full-data load, preserve runtime credentials,
and rebuild only changed image layers.

## Verified cloud evidence

Successful deployment command: `ccb258d9-633f-40ac-9637-487fb4f17110`.

- Dataset checksums and exact full-data counts passed.
- `/health` and `/ready` passed through the public proxy.
- Static UI, CSP/security headers, and session cookies passed at the public URL.
- Anonymous analytics access, unknown users, and a client-supplied role were
  rejected.
- For the same three-month overview, RLS exposed 1,706 organizations to RAM
  `U009`, 3,304 to Northeast director `U003`, and 25,561 to executive `U001`.
- Revenue was absent for the RAM and director and present for the executive.

The first two deployment attempts produced useful focused fixes. PostgreSQL
deferred foreign-key events required RLS to be re-enabled immediately after,
not inside, the bulk-load transaction. Plain Docker also required the explicit
`backend` network alias that Compose normally supplies. The failed load rolled
back; the second run completed the full data load before the container-start
failure, and the final run reused that validated state.

## Model runtime secret

The application reads `openai_api_key` from the existing Secrets Manager JSON
and never includes it in an image or repository file. If the field is absent,
health, sessions, and predefined RLS-backed analytics remain available while
model-dependent chat returns a safe HTTP 503.

Do not paste an API key into Git, Terraform variables, shell history, or chat.
Manage it through a secure AWS console or credential-management workflow, then
run `./scripts/deploy_aws.sh` again when the runtime value or application changes.

## Teardown and cost

The EC2 instance, RDS instance, Elastic IP, S3 storage, Secrets Manager secret,
and CloudWatch logs are live and billable. When the demo is no longer needed,
review the Terraform destroy plan before applying it. The demo configuration
permits immediate secret deletion and skips the final RDS snapshot; production
must use stronger retention controls.
