resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  tags = {
    Name = "${local.name_prefix}-github-actions"
  }
}

locals {
  github_oidc_subject = "repo:${var.github_repository_owner}@${var.github_repository_owner_id}/${var.github_repository}@${var.github_repository_id}:environment:${var.github_environment}"
}

data "aws_iam_policy_document" "github_deploy_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.github_oidc_subject]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${local.name_prefix}-github-deploy"
  description          = "Short-lived GitHub Actions role for immutable demo releases"
  assume_role_policy   = data.aws_iam_policy_document.github_deploy_assume_role.json
  max_session_duration = 3600

  tags = {
    Name = "${local.name_prefix}-github-deploy"
  }
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid    = "ManageImmutableReleaseObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.data.arn}/releases/app/*"]
  }

  statement {
    sid     = "DeployToDemoInstance"
    effect  = "Allow"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.app.id}",
      "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
    ]
  }

  statement {
    sid       = "ReadDeploymentCommandStatus"
    effect    = "Allow"
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.name_prefix}-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
