variable "name_prefix" {
  type        = string
  description = "Prefix applied to all resource names."
}

variable "vpc_id" {
  type        = string
  description = "VPC the instance lives in."
}

variable "subnet_id" {
  type        = string
  description = "Public subnet ID. T1 puts the EC2 directly in a public subnet (no NAT)."
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type. Must be Nitro-class (m5+, c5+, r5+, t3+) for the data-volume detection logic to work."
  default     = "m6i.xlarge"
}

variable "ami_id" {
  type        = string
  description = "AMI ID. Null falls back to the latest Amazon Linux 2023 in this region. Marketplace deployments override this with the published AMI."
  default     = null
}

variable "key_name" {
  type        = string
  description = "EC2 key pair name for SSH access. Null disables SSH (recommended; use SSM Session Manager instead)."
  default     = null
}

variable "iam_instance_profile_name" {
  type        = string
  description = "Instance profile providing Bedrock + Secrets Manager + CloudWatch Logs access."
}

variable "pg_password_secret_arn" {
  type = string
}

variable "neo4j_password_secret_arn" {
  type = string
}

variable "license_jwt_secret_arn" {
  type = string
}

variable "anthropic_api_key_secret_arn" {
  type    = string
  default = null
}

variable "openai_api_key_secret_arn" {
  type    = string
  default = null
}

variable "ai_provider" {
  type        = string
  description = "Runtime AI provider: 'bedrock' (default, IAM-based), 'anthropic' (BYO key), or 'openai' (BYO key)."
  default     = "bedrock"

  validation {
    condition     = contains(["bedrock", "anthropic", "openai"], var.ai_provider)
    error_message = "ai_provider must be one of: bedrock, anthropic, openai."
  }
}

variable "bedrock_region" {
  type        = string
  description = "AWS region used for Bedrock invocation. Null defaults to the provider region."
  default     = null
}

variable "image_registry" {
  type        = string
  description = "Container registry hostname (e.g. '<acct>.dkr.ecr.us-east-1.amazonaws.com/cast-clone')."
}

variable "image_tag" {
  type        = string
  description = "Tag applied to backend, frontend, and mcp images."
  default     = "latest"
}

variable "backend_image_name" {
  type    = string
  default = "cast-clone-backend"
}

variable "frontend_image_name" {
  type    = string
  default = "cast-clone-frontend"
}

variable "mcp_image_name" {
  type    = string
  default = "cast-clone-mcp"
}

variable "data_volume_size_gb" {
  type        = number
  description = "EBS data volume size for Postgres + Neo4j + MinIO + uploaded archives."
  default     = 100

  validation {
    condition     = var.data_volume_size_gb >= 50 && var.data_volume_size_gb <= 16000
    error_message = "data_volume_size_gb must be between 50 and 16000."
  }
}

variable "data_volume_iops" {
  type    = number
  default = 3000
}

variable "data_volume_throughput" {
  type    = number
  default = 125
}

variable "root_volume_size_gb" {
  type    = number
  default = 30
}

variable "allow_https_from_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach 443. Default is the public internet."
  default     = ["0.0.0.0/0"]
}

variable "allow_ssh_from_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach 22. Empty list disables direct SSH (recommended; use SSM)."
  default     = []
}

variable "allocate_eip" {
  type        = bool
  description = "Attach an Elastic IP. Required for a stable public URL across stop/start cycles."
  default     = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
