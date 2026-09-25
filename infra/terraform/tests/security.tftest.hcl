mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_vpc" {
    defaults = {
      id = "vpc-0123456789abcdef0"
    }
  }

  mock_data "aws_subnets" {
    defaults = {
      ids = ["subnet-00000000000000001", "subnet-00000000000000002"]
    }
  }

  mock_data "aws_ssm_parameter" {
    defaults = {
      value = "ami-0123456789abcdef0"
    }
  }

  mock_resource "aws_db_instance" {
    defaults = {
      address = "pharma.example.internal"
      port    = 5432
      master_user_secret = [{
        kms_key_id    = "arn:aws:kms:us-east-1:123456789012:key/example"
        secret_arn    = "arn:aws:secretsmanager:us-east-1:123456789012:secret:pharma"
        secret_status = "active"
      }]
    }
  }

  mock_resource "aws_eip" {
    defaults = {
      public_ip = "203.0.113.10"
    }
  }

  override_data {
    target          = data.aws_iam_policy_document.ec2_assume_role
    override_during = plan
    values = {
      json = <<-JSON
        {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sts:AssumeRole","Principal":{"Service":"ec2.amazonaws.com"}}]}
      JSON
    }
  }

  override_data {
    target          = data.aws_iam_policy_document.github_deploy_assume_role
    override_during = plan
    values = {
      json = <<-JSON
        {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sts:AssumeRoleWithWebIdentity","Principal":{"Federated":"arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"},"Condition":{"StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com","token.actions.githubusercontent.com:sub":"repo:shraddhagadale@62941237/pharma-nl2sql-assistant@1384826916:environment:demo"}}}]}
      JSON
    }
  }

  override_data {
    target          = data.aws_iam_policy_document.github_deploy
    override_during = plan
    values = {
      json = <<-JSON
        {"Version":"2012-10-17","Statement":[]}
      JSON
    }
  }

  override_data {
    target          = data.aws_iam_policy_document.app_runtime
    override_during = plan
    values = {
      json = <<-JSON
        {"Version":"2012-10-17","Statement":[]}
      JSON
    }
  }

  override_data {
    target          = data.aws_iam_policy_document.data_bucket
    override_during = plan
    values = {
      json = <<-JSON
        {"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"s3:*","Resource":"*","Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}
      JSON
    }
  }

  override_resource {
    target          = aws_security_group.app
    override_during = plan
    values = {
      id = "sg-application"
    }
  }
}

run "security_controls" {
  command = plan

  assert {
    condition     = aws_db_instance.postgres.publicly_accessible == false
    error_message = "RDS must not be publicly accessible."
  }

  assert {
    condition     = aws_db_instance.postgres.storage_encrypted
    error_message = "RDS storage must be encrypted."
  }

  assert {
    condition     = aws_db_instance.postgres.manage_master_user_password
    error_message = "RDS must manage its master password in Secrets Manager."
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.database_from_app.referenced_security_group_id == aws_security_group.app.id
    error_message = "PostgreSQL ingress must reference the application security group."
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.database_from_app.from_port == 5432 && aws_vpc_security_group_ingress_rule.database_from_app.to_port == 5432
    error_message = "The database ingress rule must be restricted to PostgreSQL port 5432."
  }

  assert {
    condition     = alltrue([for rule in values(aws_vpc_security_group_ingress_rule.app_http) : rule.from_port != 22 && rule.to_port != 22])
    error_message = "The application security group must not expose SSH."
  }

  assert {
    condition     = aws_instance.app.metadata_options[0].http_tokens == "required"
    error_message = "EC2 must require IMDSv2 tokens."
  }

  assert {
    condition     = aws_secretsmanager_secret.app_runtime.recovery_window_in_days == 0
    error_message = "The disposable demo secret should be immediately removable during teardown."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.data.block_public_acls
      && aws_s3_bucket_public_access_block.data.block_public_policy
      && aws_s3_bucket_public_access_block.data.ignore_public_acls
      && aws_s3_bucket_public_access_block.data.restrict_public_buckets
    )
    error_message = "Every S3 public-access-block control must be enabled."
  }

  assert {
    condition     = aws_iam_openid_connect_provider.github_actions.client_id_list == toset(["sts.amazonaws.com"])
    error_message = "The GitHub OIDC provider must only accept the AWS STS audience."
  }

  assert {
    condition     = local.github_oidc_subject == "repo:shraddhagadale@62941237/pharma-nl2sql-assistant@1384826916:environment:demo"
    error_message = "The deployment role trust must bind to the immutable repository IDs and demo environment."
  }

}
