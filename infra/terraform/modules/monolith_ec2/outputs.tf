output "instance_id" {
  value       = aws_instance.this.id
  description = "EC2 instance ID."
}

output "private_ip" {
  value       = aws_instance.this.private_ip
  description = "Instance private IP."
}

output "public_ip" {
  value       = var.allocate_eip ? aws_eip.this[0].public_ip : aws_instance.this.public_ip
  description = "Public IP — EIP if allocated, else the ephemeral instance IP."
}

output "public_dns" {
  value       = aws_instance.this.public_dns
  description = "AWS-assigned public DNS name."
}

output "security_group_id" {
  value       = aws_security_group.this.id
  description = "Security group ID controlling instance ingress."
}

output "data_volume_id" {
  value       = aws_ebs_volume.data.id
  description = "EBS data volume ID (Postgres + Neo4j + MinIO + archives)."
}

output "application_url" {
  value       = "https://${var.allocate_eip ? aws_eip.this[0].public_ip : aws_instance.this.public_ip}"
  description = "Self-signed HTTPS URL. First visit will show a browser certificate warning."
}
