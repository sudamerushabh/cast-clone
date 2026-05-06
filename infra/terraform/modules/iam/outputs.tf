output "application_role_arn" {
  value       = aws_iam_role.application.arn
  description = "ARN of the application role used by EC2 (T1) or ECS tasks (T2/T3)."
}

output "application_role_name" {
  value       = aws_iam_role.application.name
  description = "Name of the application role."
}

output "ec2_instance_profile_name" {
  value       = try(aws_iam_instance_profile.application[0].name, null)
  description = "EC2 instance profile name (null when not created)."
}

output "ec2_instance_profile_arn" {
  value       = try(aws_iam_instance_profile.application[0].arn, null)
  description = "EC2 instance profile ARN (null when not created)."
}

output "ecs_execution_role_arn" {
  value       = try(aws_iam_role.ecs_execution[0].arn, null)
  description = "ECS task-execution role ARN (null when not created)."
}
