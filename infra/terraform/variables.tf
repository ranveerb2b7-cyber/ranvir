variable "environment" {
  description = "staging or production"
  type        = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "region" {
  description = "AWS region. Mumbai keeps Indian customer data in India (DPDP)."
  type        = string
  default     = "ap-south-1"
}

variable "route53_zone_name" {
  description = "Existing public Route 53 hosted zone, e.g. sellerscope.in"
  type        = string
}

variable "app_hostname" {
  description = "Web app hostname, e.g. app.sellerscope.in (staging: staging.sellerscope.in)"
  type        = string
}

variable "api_hostname" {
  description = "API hostname, e.g. api.sellerscope.in"
  type        = string
}

variable "image_tag" {
  description = "Container image tag (git commit) for api and web"
  type        = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "nat_gateways" {
  description = "1 (cheaper, staging) or 2 (one per AZ, production)"
  type        = number
  default     = 1
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 50
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "db_backup_retention_days" {
  description = "Automated backups + point-in-time recovery window (1-35 days)"
  type        = number
  default     = 14
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "web_desired_count" {
  type    = number
  default = 2
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "alarm_email" {
  description = "Where CloudWatch alarms are sent (confirm the SNS subscription email)"
  type        = string
}

variable "app_config" {
  description = "Non-secret API settings (see .env.example), e.g. AUTH_JWT_ISSUER, SMTP_HOST"
  type        = map(string)
  default     = {}
}

variable "secret_names" {
  description = <<-EOT
    Settings read from AWS Secrets Manager (create the secrets BEFORE apply; values never
    pass through Terraform or its state). Map of ENV_VAR => secret name.
  EOT
  type        = map(string)
  default = {
    DATABASE_URL           = "sellerscope/DATABASE_URL"
    MIGRATION_DATABASE_URL = "sellerscope/MIGRATION_DATABASE_URL"
    REDIS_URL              = "sellerscope/REDIS_URL"
    SMTP_PASSWORD          = "sellerscope/SMTP_PASSWORD"
    METRICS_TOKEN          = "sellerscope/METRICS_TOKEN"
  }
}

variable "redis_auth_secret_name" {
  description = "Secrets Manager secret holding the Redis AUTH token (16-128 chars)"
  type        = string
  default     = "sellerscope/REDIS_AUTH_TOKEN"
}

variable "db_master_secret_name" {
  description = "Secrets Manager secret holding the RDS master password"
  type        = string
  default     = "sellerscope/DB_MASTER_PASSWORD"
}
