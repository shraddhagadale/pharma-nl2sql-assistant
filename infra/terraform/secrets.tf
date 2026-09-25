resource "aws_secretsmanager_secret" "app_runtime" {
  name                    = "${local.name_prefix}/app-runtime"
  description             = "Runtime database credentials, session secret, and optional model API key"
  recovery_window_in_days = var.environment == "demo" ? 0 : 7

  tags = {
    Name = "${local.name_prefix}-app-runtime"
  }
}
