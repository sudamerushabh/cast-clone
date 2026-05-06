output "application_url" {
  value       = module.monolith.application_url
  description = "HTTPS URL for the cast-clone UI (self-signed cert; expect a browser warning on first visit)."
}

output "instance_id" {
  value       = module.monolith.instance_id
  description = "EC2 instance ID."
}

output "public_ip" {
  value       = module.monolith.public_ip
  description = "Elastic IP of the instance."
}

output "ssm_session_command" {
  value       = "aws ssm start-session --target ${module.monolith.instance_id} --region ${var.aws_region}"
  description = "Open a shell on the instance via SSM Session Manager (no SSH key required)."
}

output "license_secret_arn" {
  value       = module.secrets.license_jwt_secret_arn
  description = "Update this secret value with the production license JWT after purchase, then 'systemctl restart cast-clone' on the instance."
}

output "data_volume_id" {
  value       = module.monolith.data_volume_id
  description = "EBS data volume ID."
}

output "backup_vault_arn" {
  value       = aws_backup_vault.this.arn
  description = "AWS Backup vault holding daily EBS snapshots."
}
