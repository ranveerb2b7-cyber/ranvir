# Infrastructure (AWS ap-south-1)

Terraform for the staging and production stacks:
- **Network:** VPC with public and private subnets and NAT.
- **Database:** RDS PostgreSQL 16 (encrypted, TLS-only, point-in-time recovery, Multi-AZ in production).
- **Cache:** ElastiCache Redis (TLS + AUTH).
- **Files:** S3 buckets for files and backups (SSE-KMS, TLS-only, versioned).
- **Containers:** ECR and an ECS Fargate cluster running api, worker, beat (exactly one), web and a one-off migrate task.
- **Edge:** ALB with an ACM certificate (TLS 1.2+); `/metrics` is blocked from the internet.
- **Ops:** CloudWatch logs and alarms to SNS email; one KMS key per environment.

**Status:** `terraform validate` passes (Terraform 1.17.1, AWS provider 6.72; checked in CI). **It has not been applied to an AWS account**, so expect first-apply fixes. Follow [docs/runbooks/deploy.md](../../docs/runbooks/deploy.md).

Secrets are read from AWS Secrets Manager by name; their values never go through Terraform variables. The one exception is the RDS master password and Redis AUTH token, which are read through data sources and so do end up in the (encrypted) state file. Restrict access to the state bucket accordingly.
