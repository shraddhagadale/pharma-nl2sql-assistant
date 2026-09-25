output "aws_region" {
  description = "AWS region containing the demo stack."
  value       = var.aws_region
}

output "app_public_ip" {
  description = "Stable public IPv4 address of the demo EC2 instance."
  value       = aws_eip.app.public_ip
}

output "app_health_url" {
  description = "Public application health endpoint."
  value       = "http://${aws_eip.app.public_ip}/health"
}

output "app_url" {
  description = "Public HTTP URL for the demo application."
  value       = "http://${aws_eip.app.public_ip}"
}

output "rds_address" {
  description = "Private RDS hostname, reachable from the application security group."
  value       = aws_db_instance.postgres.address
}

output "rds_port" {
  description = "RDS PostgreSQL port."
  value       = aws_db_instance.postgres.port
}

output "database_secret_arn" {
  description = "Secrets Manager ARN for the RDS-managed master credential."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "app_runtime_secret_arn" {
  description = "Secrets Manager ARN for application runtime credentials and optional model API key."
  value       = aws_secretsmanager_secret.app_runtime.arn
}

output "data_bucket_name" {
  description = "Private S3 bucket for generated CSV staging."
  value       = aws_s3_bucket.data.id
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for bootstrap and application logs."
  value       = aws_cloudwatch_log_group.app.name
}

output "ssm_instance_id" {
  description = "EC2 instance ID to use with Systems Manager Session Manager."
  value       = aws_instance.app.id
}
