variable "aws_region" {
  description = "AWS region for all demo resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short project name used in resource names and tags."
  type        = string
  default     = "pharma-nl2sql"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.project_name))
    error_message = "project_name must be 3-24 lowercase letters, numbers, or hyphens and start with a letter."
  }
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "demo"

  validation {
    condition     = contains(["demo", "dev", "staging", "prod"], var.environment)
    error_message = "environment must be demo, dev, staging, or prod."
  }
}

variable "ec2_instance_type" {
  description = "EC2 instance size for the containerized application."
  type        = string
  default     = "t3.small"
}

variable "allowed_http_cidrs" {
  description = "IPv4 CIDRs allowed to reach the demo HTTP health endpoint."
  type        = set(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition     = length(var.allowed_http_cidrs) > 0 && alltrue([for cidr in var.allowed_http_cidrs : can(cidrnetmask(cidr))])
    error_message = "allowed_http_cidrs must contain at least one valid IPv4 CIDR."
  }
}

variable "db_name" {
  description = "Initial PostgreSQL database name."
  type        = string
  default     = "pharma"

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_]{0,62}$", var.db_name))
    error_message = "db_name must be a valid PostgreSQL identifier of at most 63 characters."
  }
}

variable "db_username" {
  description = "RDS master username used only for migrations and role bootstrap."
  type        = string
  default     = "pharma_admin"

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_]{0,62}$", var.db_username))
    error_message = "db_username must start with a letter and contain only letters, numbers, or underscores."
  }
}

variable "postgres_major_version" {
  description = "RDS PostgreSQL major engine version."
  type        = string
  default     = "16"
}

variable "db_instance_class" {
  description = "RDS instance size for the demo database."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "Initial encrypted RDS storage in GiB."
  type        = number
  default     = 20

  validation {
    condition     = var.db_allocated_storage_gb >= 20
    error_message = "db_allocated_storage_gb must be at least 20 GiB."
  }
}

variable "db_max_allocated_storage_gb" {
  description = "Maximum storage autoscaling threshold in GiB."
  type        = number
  default     = 100

  validation {
    condition     = var.db_max_allocated_storage_gb >= var.db_allocated_storage_gb
    error_message = "db_max_allocated_storage_gb must be greater than or equal to initial storage."
  }
}

variable "backup_retention_days" {
  description = "Automated RDS backup retention."
  type        = number
  default     = 1

  validation {
    condition     = var.backup_retention_days >= 0 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 0 and 35."
  }
}

variable "deletion_protection" {
  description = "Protect RDS from deletion. Disabled by default for the disposable demo."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Skip the final RDS snapshot when destroying the disposable demo."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention period."
  type        = number
  default     = 14
}
