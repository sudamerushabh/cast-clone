locals {
  base_tags = merge(var.tags, { Module = "cast-clone-iam" })
}

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# ---------- Application role (assumed by EC2 in T1, ECS task in T2/T3) ----------

data "aws_iam_policy_document" "application_assume" {
  dynamic "statement" {
    for_each = var.create_ec2_instance_profile ? [1] : []
    content {
      effect  = "Allow"
      actions = ["sts:AssumeRole"]
      principals {
        type        = "Service"
        identifiers = ["ec2.amazonaws.com"]
      }
    }
  }

  dynamic "statement" {
    for_each = var.create_ecs_task_role ? [1] : []
    content {
      effect  = "Allow"
      actions = ["sts:AssumeRole"]
      principals {
        type        = "Service"
        identifiers = ["ecs-tasks.amazonaws.com"]
      }
    }
  }
}

resource "aws_iam_role" "application" {
  name               = "${var.name_prefix}-application"
  assume_role_policy = data.aws_iam_policy_document.application_assume.json
  tags               = local.base_tags
}

# SSM Session Manager + run-command — required so operators can shell into the instance
# without an SSH key, and so AWS Backup / SSM Patch Manager can act on it.
resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.application.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ECR pull — required for the direct-deploy path (Terraform tier roots) where the EC2
# pulls cast-clone images from a private registry on first boot. Marketplace AMI deployments
# bake images into the AMI and don't use this, but it's read-only and harmless to attach.
resource "aws_iam_role_policy_attachment" "ecr_read_only" {
  role       = aws_iam_role.application.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Bedrock invoke
data "aws_iam_policy_document" "bedrock" {
  statement {
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.bedrock_model_arns
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "bedrock-invoke"
  role   = aws_iam_role.application.id
  policy = data.aws_iam_policy_document.bedrock.json
}

# Secrets read
data "aws_iam_policy_document" "secrets_read" {
  count = length(var.secret_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = var.secret_arns
  }
}

resource "aws_iam_role_policy" "secrets_read" {
  count  = length(var.secret_arns) > 0 ? 1 : 0
  name   = "secrets-read"
  role   = aws_iam_role.application.id
  policy = data.aws_iam_policy_document.secrets_read[0].json
}

# S3 archives (uploaded codebases) — T2/T3
data "aws_iam_policy_document" "s3" {
  count = length(var.s3_bucket_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = var.s3_bucket_arns
  }

  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = [for arn in var.s3_bucket_arns : "${arn}/*"]
  }
}

resource "aws_iam_role_policy" "s3" {
  count  = length(var.s3_bucket_arns) > 0 ? 1 : 0
  name   = "s3-archives"
  role   = aws_iam_role.application.id
  policy = data.aws_iam_policy_document.s3[0].json
}

# CloudWatch Logs (scoped to the cast-clone log-group prefix)
data "aws_iam_policy_document" "logs" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:${var.log_group_prefix}/*",
      "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:${var.log_group_prefix}/*:log-stream:*",
    ]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "cloudwatch-logs"
  role   = aws_iam_role.application.id
  policy = data.aws_iam_policy_document.logs.json
}

# EC2 instance profile (T1 wraps the application role)
resource "aws_iam_instance_profile" "application" {
  count = var.create_ec2_instance_profile ? 1 : 0
  name  = "${var.name_prefix}-application"
  role  = aws_iam_role.application.name
  tags  = local.base_tags
}

# ---------- ECS task-execution role (T2/T3) ----------
# Distinct from the application role: this role is used by ECS itself (image pulls, log writes,
# secret-to-env-var injection at task start), not by the application code at runtime.

data "aws_iam_policy_document" "ecs_execution_assume" {
  count = var.create_ecs_execution_role ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  count              = var.create_ecs_execution_role ? 1 : 0
  name               = "${var.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_execution_assume[0].json
  tags               = local.base_tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  count      = var.create_ecs_execution_role ? 1 : 0
  role       = aws_iam_role.ecs_execution[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  count  = var.create_ecs_execution_role && length(var.secret_arns) > 0 ? 1 : 0
  name   = "secrets-read"
  role   = aws_iam_role.ecs_execution[0].id
  policy = data.aws_iam_policy_document.secrets_read[0].json
}
