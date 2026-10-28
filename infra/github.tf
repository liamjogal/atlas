# GitHub Actions authenticates with short-lived OIDC credentials: no AWS keys stored anywhere.
# Only workflows on this repository's master branch (deploy, Run ETL) can assume the role.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/master"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.project}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "deploy-and-run-etl"
  role = aws_iam_role.github_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PushImages"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart",
        ]
        Resource = aws_ecr_repository.atlas.arn
      },
      {
        Sid    = "DeployAndRunTasks"
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition", "ecs:DescribeServices",
          "ecs:UpdateService", "ecs:RunTask", "ecs:DescribeTasks", "ecs:ListTasks",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task_execution.arn, aws_iam_role.task.arn]
      },
      {
        Sid      = "ReadEtlLogs"
        Effect   = "Allow"
        Action   = ["logs:GetLogEvents", "logs:FilterLogEvents", "logs:DescribeLogStreams"]
        Resource = ["${aws_cloudwatch_log_group.etl.arn}:*", "${aws_cloudwatch_log_group.api.arn}:*"]
      },
    ]
  })
}

# --- Terraform from GitHub ----------------------------------------------------------------------
# Pull requests that touch infra/ get a read-only plan posted as a comment; applying requires the
# `production` GitHub environment, which needs your approval in GitHub before the job can start.
# (Fork PRs never receive OIDC tokens, so outside contributors can't use either role.)

data "aws_iam_policy_document" "github_terraform_plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:pull_request"]
    }
  }
}

resource "aws_iam_role" "github_terraform_plan" {
  name               = "${var.project}-github-terraform-plan"
  assume_role_policy = data.aws_iam_policy_document.github_terraform_plan_assume.json
}

# Read everything, change nothing...
resource "aws_iam_role_policy_attachment" "github_terraform_plan_read" {
  role       = aws_iam_role.github_terraform_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ...except what `terraform plan` itself needs: the state lock file, and reading the generated
# secret values it compares against.
resource "aws_iam_role_policy" "github_terraform_plan_state" {
  name = "terraform-state"
  role = aws_iam_role.github_terraform_plan.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "arn:aws:s3:::atlas-tfstate-${data.aws_caller_identity.current.account_id}/atlas/*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:${var.project}/*"
      },
    ]
  })
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "github_terraform_apply_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs running in the approval-gated `production` environment get this token subject.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:production"]
    }
  }
}

resource "aws_iam_role" "github_terraform_apply" {
  name               = "${var.project}-github-terraform-apply"
  assume_role_policy = data.aws_iam_policy_document.github_terraform_apply_assume.json
}

# Terraform manages IAM, networking, databases and more, so applying needs broad rights. The
# protection is who can assume it: the production environment, after your approval.
resource "aws_iam_role_policy_attachment" "github_terraform_apply_admin" {
  role       = aws_iam_role.github_terraform_apply.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
