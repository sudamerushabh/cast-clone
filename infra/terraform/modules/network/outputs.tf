output "vpc_id" {
  value       = local.create ? aws_vpc.this[0].id : data.aws_vpc.adopted[0].id
  description = "VPC ID (created or adopted)."
}

output "vpc_cidr_block" {
  value       = local.create ? aws_vpc.this[0].cidr_block : data.aws_vpc.adopted[0].cidr_block
  description = "VPC CIDR block."
}

output "public_subnet_ids" {
  value       = local.create ? aws_subnet.public[*].id : var.public_subnet_ids
  description = "Public subnet IDs across AZs."
}

output "private_subnet_ids" {
  value       = local.create ? aws_subnet.private[*].id : var.private_subnet_ids
  description = "Private subnet IDs across AZs."
}

output "availability_zones" {
  value       = local.create ? local.azs : [for s in data.aws_subnet.adopted_private : s.availability_zone]
  description = "AZs the subnets reside in."
}

output "nat_gateway_ids" {
  value       = aws_nat_gateway.this[*].id
  description = "NAT gateway IDs (empty when not created or when adopting)."
}

output "internet_gateway_id" {
  value       = local.create ? aws_internet_gateway.this[0].id : null
  description = "Internet gateway ID (null when adopting)."
}
