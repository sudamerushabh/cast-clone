variable "name_prefix" {
  type        = string
  description = "Prefix for secret paths (e.g., 'castclone-prod' yields 'castclone-prod/postgres/password')."
}

variable "kms_key_id" {
  type        = string
  description = "KMS key ID/ARN for secret encryption. Null uses the AWS-managed key 'aws/secretsmanager'."
  default     = null
}

variable "recovery_window_in_days" {
  type        = number
  description = "Days before deleted secrets are permanently removed. Set 0 for immediate deletion."
  default     = 7

  validation {
    condition     = var.recovery_window_in_days == 0 || (var.recovery_window_in_days >= 7 && var.recovery_window_in_days <= 30)
    error_message = "recovery_window_in_days must be 0, or between 7 and 30."
  }
}

variable "generate_pg_password" {
  type        = bool
  description = "Generate a random Postgres password."
  default     = true
}

variable "pg_password_override" {
  type        = string
  description = "Explicit Postgres password (skips random generation when set)."
  default     = null
  sensitive   = true
}

variable "generate_neo4j_password" {
  type        = bool
  description = "Generate a random Neo4j password."
  default     = true
}

variable "neo4j_password_override" {
  type        = string
  description = "Explicit Neo4j password (skips random generation when set)."
  default     = null
  sensitive   = true
}

variable "license_jwt" {
  type        = string
  description = "Cast-Clone license JWT. Null seeds 'TRIAL_PLACEHOLDER' which the app interprets as trial-on-first-boot."
  default     = null
  sensitive   = true
}

variable "anthropic_api_key" {
  type        = string
  description = "Optional Anthropic API key. Skipped when null."
  default     = null
  sensitive   = true
}

variable "openai_api_key" {
  type        = string
  description = "Optional OpenAI API key. Skipped when null."
  default     = null
  sensitive   = true
}

variable "tags" {
  type        = map(string)
  description = "Tags merged into every resource."
  default     = {}
}
