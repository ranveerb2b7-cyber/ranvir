output "app_url" {
  value = "https://${var.app_hostname}"
}

output "api_url" {
  value = "https://${var.api_hostname}/api/v1"
}

output "ecr_repositories" {
  value = { for k, r in aws_ecr_repository.app : k => r.repository_url }
}

output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "redis_endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "files_bucket" {
  value = aws_s3_bucket.files.bucket
}

output "backups_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "migrate_task_definition" {
  description = "Run before each deploy: aws ecs run-task (see docs/runbooks/deploy.md)"
  value       = aws_ecs_task_definition.backend["migrate"].arn
}

output "private_subnets" {
  value = aws_subnet.private[*].id
}

output "services_security_group" {
  value = aws_security_group.services.id
}
