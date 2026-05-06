locals {
  base_tags = merge(var.tags, { Module = "cast-clone-secrets" })
}

# Generated passwords use alphanumeric characters only (no special characters).
# Rationale: every special character we considered safe at one layer broke at another:
#   - '$'  : docker-compose .env variable substitution
#   - '%'  : Python configparser INI interpolation (alembic.ini)
#   - ':/@?&#' : URI component delimiters
#   - '<>(){}[]"\\' : shell / YAML metacharacters
# 62 alphanumerics × 32 chars = ~190 bits of entropy — more than NIST's strictest
# recommendation. The few bits gained from special chars don't justify the operational
# fragility of "did I check every parser this string passes through?"

# ---------- Postgres ----------

resource "random_password" "pg" {
  count            = var.generate_pg_password && var.pg_password_override == null ? 1 : 0
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "pg_password" {
  name                    = "${var.name_prefix}/postgres/password"
  description             = "PostgreSQL master password for cast-clone."
  kms_key_id              = var.kms_key_id
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = local.base_tags
}

resource "aws_secretsmanager_secret_version" "pg_password" {
  secret_id     = aws_secretsmanager_secret.pg_password.id
  secret_string = coalesce(var.pg_password_override, try(random_password.pg[0].result, ""))
}

# ---------- Neo4j ----------

resource "random_password" "neo4j" {
  count            = var.generate_neo4j_password && var.neo4j_password_override == null ? 1 : 0
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "neo4j_password" {
  name                    = "${var.name_prefix}/neo4j/password"
  description             = "Neo4j password for cast-clone."
  kms_key_id              = var.kms_key_id
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = local.base_tags
}

resource "aws_secretsmanager_secret_version" "neo4j_password" {
  secret_id     = aws_secretsmanager_secret.neo4j_password.id
  secret_string = coalesce(var.neo4j_password_override, try(random_password.neo4j[0].result, ""))
}

# ---------- License JWT ----------

resource "aws_secretsmanager_secret" "license_jwt" {
  name                    = "${var.name_prefix}/license/jwt"
  description             = "Cast-Clone license JWT (trial or production). 'TRIAL_PLACEHOLDER' triggers trial-on-first-boot."
  kms_key_id              = var.kms_key_id
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = local.base_tags
}

resource "aws_secretsmanager_secret_version" "license_jwt" {
  secret_id     = aws_secretsmanager_secret.license_jwt.id
  secret_string = var.license_jwt == null ? "TRIAL_PLACEHOLDER" : var.license_jwt
}

# ---------- Optional AI keys ----------

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  count                   = var.anthropic_api_key != null ? 1 : 0
  name                    = "${var.name_prefix}/ai/anthropic-api-key"
  description             = "Customer-provided Anthropic API key (overrides Bedrock at runtime)."
  kms_key_id              = var.kms_key_id
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = local.base_tags
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  count         = var.anthropic_api_key != null ? 1 : 0
  secret_id     = aws_secretsmanager_secret.anthropic_api_key[0].id
  secret_string = var.anthropic_api_key
}

resource "aws_secretsmanager_secret" "openai_api_key" {
  count                   = var.openai_api_key != null ? 1 : 0
  name                    = "${var.name_prefix}/ai/openai-api-key"
  description             = "Customer-provided OpenAI API key (overrides Bedrock at runtime)."
  kms_key_id              = var.kms_key_id
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = local.base_tags
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  count         = var.openai_api_key != null ? 1 : 0
  secret_id     = aws_secretsmanager_secret.openai_api_key[0].id
  secret_string = var.openai_api_key
}
