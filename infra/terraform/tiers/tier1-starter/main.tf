locals {
  common_tags = {
    Project     = "cast-clone"
    ManagedBy   = "terraform"
    Tier        = "t1-starter"
    Environment = var.environment
  }
}

module "network" {
  source = "../../modules/network"

  name_prefix        = var.name_prefix
  enable_nat_gateway = false # T1 puts the EC2 in a public subnet; no private subnets need NAT

  tags = local.common_tags
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix       = var.name_prefix
  license_jwt       = var.license_jwt
  anthropic_api_key = var.anthropic_api_key
  openai_api_key    = var.openai_api_key

  tags = local.common_tags
}

module "iam" {
  source = "../../modules/iam"

  name_prefix                 = var.name_prefix
  create_ec2_instance_profile = true
  secret_arns                 = module.secrets.all_secret_arns

  tags = local.common_tags
}

module "monolith" {
  source = "../../modules/monolith_ec2"

  name_prefix               = var.name_prefix
  vpc_id                    = module.network.vpc_id
  subnet_id                 = module.network.public_subnet_ids[0]
  instance_type             = var.instance_type
  data_volume_size_gb       = var.data_volume_size_gb
  iam_instance_profile_name = module.iam.ec2_instance_profile_name
  key_name                  = var.key_name

  pg_password_secret_arn       = module.secrets.pg_password_secret_arn
  neo4j_password_secret_arn    = module.secrets.neo4j_password_secret_arn
  license_jwt_secret_arn       = module.secrets.license_jwt_secret_arn
  anthropic_api_key_secret_arn = module.secrets.anthropic_api_key_secret_arn
  openai_api_key_secret_arn    = module.secrets.openai_api_key_secret_arn
  ai_provider                  = var.ai_provider

  image_registry = var.image_registry
  image_tag      = var.image_tag

  allow_https_from_cidrs = var.allow_https_from_cidrs
  allow_ssh_from_cidrs   = var.allow_ssh_from_cidrs

  tags = local.common_tags
}

# ---------- AWS Backup ----------
# Backs up every resource tagged CastCloneBackup=true (the data EBS volume + root volume).
# Inline here for now; will be extracted to modules/backups when T2/T3 also need it.

resource "aws_backup_vault" "this" {
  name = "${var.name_prefix}-vault"
  tags = local.common_tags
}

resource "aws_iam_role" "backup" {
  name = "${var.name_prefix}-backup-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "backup.amazonaws.com" }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_backup_plan" "this" {
  name = "${var.name_prefix}-daily"

  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.this.name
    schedule          = "cron(0 5 ? * * *)" # 05:00 UTC daily

    lifecycle {
      delete_after = var.backup_retention_days
    }
  }

  tags = local.common_tags
}

resource "aws_backup_selection" "this" {
  iam_role_arn = aws_iam_role.backup.arn
  name         = "${var.name_prefix}-tagged"
  plan_id      = aws_backup_plan.this.id

  selection_tag {
    type  = "STRINGEQUALS"
    key   = "CastCloneBackup"
    value = "true"
  }
}
