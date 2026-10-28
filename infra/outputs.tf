output "url" {
  description = "The public site."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "ecr_repository" {
  value = aws_ecr_repository.atlas.repository_url
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "etl_capacity_provider" {
  value = aws_ecs_capacity_provider.etl.name
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.github_deploy.arn
}

output "etl_schedules" {
  description = "Active automatic ETL schedules (empty = manual only)."
  value       = { for name, schedule in aws_scheduler_schedule.etl : name => schedule.schedule_expression }
}

output "github_terraform_plan_role_arn" {
  description = "Set as the TERRAFORM_PLAN_ROLE_ARN repository variable."
  value       = aws_iam_role.github_terraform_plan.arn
}

output "github_terraform_apply_role_arn" {
  description = "Set as the TERRAFORM_APPLY_ROLE_ARN repository variable."
  value       = aws_iam_role.github_terraform_apply.arn
}
