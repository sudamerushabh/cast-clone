output "pg_password_secret_arn" {
  value       = aws_secretsmanager_secret.pg_password.arn
  description = "Secrets Manager ARN holding the Postgres password."
}

output "neo4j_password_secret_arn" {
  value       = aws_secretsmanager_secret.neo4j_password.arn
  description = "Secrets Manager ARN holding the Neo4j password."
}

output "license_jwt_secret_arn" {
  value       = aws_secretsmanager_secret.license_jwt.arn
  description = "Secrets Manager ARN holding the cast-clone license JWT."
}

output "anthropic_api_key_secret_arn" {
  value       = try(aws_secretsmanager_secret.anthropic_api_key[0].arn, null)
  description = "Secrets Manager ARN for the Anthropic API key (null if not provided)."
}

output "openai_api_key_secret_arn" {
  value       = try(aws_secretsmanager_secret.openai_api_key[0].arn, null)
  description = "Secrets Manager ARN for the OpenAI API key (null if not provided)."
}

output "all_secret_arns" {
  value = concat(
    [
      aws_secretsmanager_secret.pg_password.arn,
      aws_secretsmanager_secret.neo4j_password.arn,
      aws_secretsmanager_secret.license_jwt.arn,
    ],
    aws_secretsmanager_secret.anthropic_api_key[*].arn,
    aws_secretsmanager_secret.openai_api_key[*].arn,
  )
  description = "Convenience list of every secret ARN (used by the iam module to scope policies). Length is statically determinable from var.anthropic_api_key / var.openai_api_key — concat+splat pattern keeps Terraform's plan-time analysis happy."
}
