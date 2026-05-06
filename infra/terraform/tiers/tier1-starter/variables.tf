variable "aws_region" {
  type        = string
  description = "AWS region to deploy into."
  default     = "us-east-1"
}

variable "name_prefix" {
  type        = string
  description = "Prefix applied to all resource names. Lowercase + hyphens recommended."
  default     = "castclone-t1"
}

variable "environment" {
  type    = string
  default = "prod"
}

# ----- Sizing -----

variable "instance_type" {
  type        = string
  description = "EC2 instance type. See sizing matrix in README."
  default     = "m6i.xlarge"
}

variable "data_volume_size_gb" {
  type        = number
  description = "EBS data volume size (Postgres + Neo4j + MinIO + archives)."
  default     = 100
}

# ----- Container images -----

variable "image_registry" {
  type        = string
  description = "Container registry hostname (e.g. '<acct>.dkr.ecr.us-east-1.amazonaws.com/cast-clone')."
}

variable "image_tag" {
  type        = string
  description = "Tag applied to backend, frontend, mcp images."
  default     = "latest"
}

# ----- Network exposure -----

variable "allow_https_from_cidrs" {
  type        = list(string)
  description = "CIDRs allowed on 443. Default is the public internet."
  default     = ["0.0.0.0/0"]
}

variable "allow_ssh_from_cidrs" {
  type        = list(string)
  description = "CIDRs allowed on 22. Empty list disables direct SSH (recommended; use SSM)."
  default     = []
}

variable "key_name" {
  type        = string
  description = "EC2 key pair name (required only when allow_ssh_from_cidrs is non-empty)."
  default     = null
}

# ----- AI -----

variable "ai_provider" {
  type        = string
  description = "Runtime AI provider: 'bedrock' (default), 'anthropic', or 'openai'."
  default     = "bedrock"
}

variable "anthropic_api_key" {
  type      = string
  default   = null
  sensitive = true
}

variable "openai_api_key" {
  type      = string
  default   = null
  sensitive = true
}

# ----- License -----

variable "license_jwt" {
  type        = string
  description = "Production license JWT. Leave null to start in trial mode."
  default     = null
  sensitive   = true
}

# ----- Backups -----

variable "backup_retention_days" {
  type        = number
  description = "Days to retain daily EBS snapshots."
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 365
    error_message = "backup_retention_days must be between 1 and 365."
  }
}
