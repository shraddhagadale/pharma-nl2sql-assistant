# AWS demo infrastructure

This Terraform root module creates the Phase 4/Checkpoint 2 AWS foundation:

- one Amazon Linux 2023 EC2 instance with an Elastic IP
- one non-public RDS PostgreSQL instance
- an RDS-managed master password in Secrets Manager
- a separate application-runtime secret whose value is initialized on EC2
- one private, encrypted, versioned S3 data-staging bucket
- one CloudWatch log group and the CloudWatch agent
- Systems Manager Session Manager access instead of SSH
- security groups allowing PostgreSQL only from the EC2 application group

It intentionally uses the selected region's default VPC and default subnets. It does not create a custom VPC, NAT gateway, bastion host, or VPC endpoints.

## Prerequisites

- Terraform 1.8 or newer
- AWS credentials with permission to manage the resources above
- a default VPC with default subnets in at least two Availability Zones
- an AWS account where the selected EC2 and RDS instance types are available

Authenticate with a named AWS profile, IAM Identity Center, or temporary environment credentials. Do not put access keys in `.tfvars` or commit them.

## Review and plan

Run the repository validation wrapper without installing Terraform globally:

```bash
./scripts/validate_infra.sh
```

Or use an installed Terraform CLI directly:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform fmt -check -recursive
terraform validate
terraform test
terraform plan -out=demo.tfplan
```

Review the plan before applying it. EC2, RDS, storage, public IPv4, logs, and data transfer can incur AWS charges.

## Apply and verify

```bash
terraform apply demo.tfplan
terraform output
curl "$(terraform output -raw app_health_url)"
```

The expected health response is `ok`. Use the `ssm_instance_id` output with Session Manager for shell access; port 22 is not opened.

## Deploy the application

After generating the full CSV dataset, run:

```bash
./scripts/deploy_aws.sh
```

The wrapper stages source and data in the private bucket, runs the release over
Systems Manager, initializes runtime secret values on EC2, loads or verifies the
full RDS dataset, starts the two application containers, and runs the public
smoke test. See `docs/deployment.md` for the verified result and recovery notes.

A trusted HTTPS endpoint requires a domain and certificate/reverse-proxy or
load-balancer decision. The synthetic demo remains HTTP-only and does not fake
trust with a self-signed certificate.

## Database access

RDS has no public address. Its security group accepts TCP 5432 only from the EC2 security group. Retrieve the RDS-managed credential from Secrets Manager on the EC2 instance using its IAM role, then run migrations and bulk-load data from EC2/S3.

The initial RDS master credential is only for migrations, full-data loading,
and database-role bootstrap. The request-serving backend uses separate auth,
limited, and executive runtime logins whose random passwords are held in the
application-runtime secret.

## State

Local state is ignored. Before collaborative or production use, copy `backend.tf.example` to `backend.tf` and point it to a separately bootstrapped encrypted state bucket and lock table. The application data bucket cannot bootstrap its own Terraform backend.

## Teardown

The demo defaults to `deletion_protection = false` and `skip_final_snapshot = true` for straightforward teardown. Confirm those values are appropriate before running:

```bash
terraform destroy
```

Production should enable deletion protection, retain final snapshots, use dedicated private subnets, and store Terraform state remotely.
