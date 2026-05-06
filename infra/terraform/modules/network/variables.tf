variable "name_prefix" {
  type        = string
  description = "Prefix applied to all resource names (e.g., 'castclone-prod')."
}

variable "create_vpc" {
  type        = bool
  description = "Create a new VPC. When false, adopt an existing VPC via vpc_id + subnet inputs."
  default     = true
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC (only used when create_vpc=true). Must be /16 to fit the subnet plan."
  default     = "10.42.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && tonumber(split("/", var.vpc_cidr)[1]) == 16
    error_message = "vpc_cidr must be a valid /16 CIDR block."
  }
}

variable "availability_zone_count" {
  type        = number
  description = "Number of AZs to span (only when create_vpc=true)."
  default     = 2

  validation {
    condition     = var.availability_zone_count >= 2 && var.availability_zone_count <= 4
    error_message = "availability_zone_count must be between 2 and 4."
  }
}

variable "enable_nat_gateway" {
  type        = bool
  description = "Provision NAT gateway(s) for private subnets. Set false for T1 (single EC2 in public subnet)."
  default     = true
}

variable "single_nat_gateway" {
  type        = bool
  description = "When true, one NAT serves all private subnets (cheaper). When false, one NAT per AZ (HA)."
  default     = true
}

variable "vpc_id" {
  type        = string
  description = "Existing VPC ID to adopt (only when create_vpc=false)."
  default     = null
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Existing public subnet IDs (only when create_vpc=false)."
  default     = []
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Existing private subnet IDs (only when create_vpc=false)."
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Tags merged into every resource."
  default     = {}
}
