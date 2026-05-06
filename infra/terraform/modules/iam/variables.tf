variable "name_prefix" {
  type        = string
  description = "Prefix for IAM resource names."
}

variable "create_ec2_instance_profile" {
  type        = bool
  description = "Create an EC2 instance profile wrapping the application role (T1)."
  default     = false
}

variable "create_ecs_task_role" {
  type        = bool
  description = "Allow ECS tasks to assume the application role (T2/T3)."
  default     = false
}

variable "create_ecs_execution_role" {
  type        = bool
  description = "Create the separate ECS task-execution role used by ECS itself for image pulls + log writes + secret injection (T2/T3)."
  default     = false
}

variable "bedrock_model_arns" {
  type        = list(string)
  description = "Bedrock foundation-model ARNs the application may invoke. Defaults to all Anthropic models in any region."
  default     = ["arn:aws:bedrock:*::foundation-model/anthropic.*"]
}

variable "secret_arns" {
  type        = list(string)
  description = "Secrets Manager ARNs the application reads at runtime (typically module.secrets.all_secret_arns)."
  default     = []
}

variable "s3_bucket_arns" {
  type        = list(string)
  description = "S3 bucket ARNs the application reads/writes (codebase archives in T2/T3)."
  default     = []
}

variable "log_group_prefix" {
  type        = string
  description = "CloudWatch Logs prefix the application is allowed to write to."
  default     = "/cast-clone"
}

variable "tags" {
  type        = map(string)
  description = "Tags merged into every resource."
  default     = {}
}
