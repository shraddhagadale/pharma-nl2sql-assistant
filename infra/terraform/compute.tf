resource "aws_instance" "app" {
  ami           = data.aws_ssm_parameter.amazon_linux_2023.value
  instance_type = var.ec2_instance_type
  subnet_id     = sort(data.aws_subnets.default.ids)[0]

  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region          = var.aws_region
    data_bucket         = aws_s3_bucket.data.id
    database_host       = aws_db_instance.postgres.address
    database_name       = var.db_name
    database_port       = aws_db_instance.postgres.port
    database_secret_arn = aws_db_instance.postgres.master_user_secret[0].secret_arn
    log_group_name      = aws_cloudwatch_log_group.app.name
    project_name        = var.project_name
  })

  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 20
  }

  lifecycle {
    precondition {
      condition     = length(data.aws_subnets.default.ids) > 0
      error_message = "The selected AWS region must have at least one default subnet."
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.app_runtime,
    aws_iam_role_policy_attachment.cloudwatch_agent,
    aws_iam_role_policy_attachment.ssm,
  ]

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id

  tags = {
    Name = "${local.name_prefix}-app"
  }
}
