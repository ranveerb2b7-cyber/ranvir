# Deploy

Target: AWS **ap-south-1 (Mumbai)**, defined in `infra/terraform`. Containers run on ECS Fargate behind an ALB with TLS 1.2+; PostgreSQL 16 on RDS; Redis on ElastiCache (TLS + AUTH); files on S3 (SSE-KMS). There are separate `staging` and `production` stacks (separate VPCs, databases, buckets, KMS keys).

## First-time setup (per environment) ⚠
1. **Prerequisites:**
   - An AWS account with an admin role.
   - A Route 53 hosted zone for your domain.
   - An S3 bucket for Terraform state.
   - Amazon SES in ap-south-1, out of sandbox, with the sending domain verified (DKIM, SPF, DMARC).
   - A hosted Supabase project in the Mumbai region (staging and production separate).
2. **Create the secrets in AWS Secrets Manager** (values never pass through Terraform):
   - `sellerscope/DB_MASTER_PASSWORD`: random, 32+ characters.
   - `sellerscope/REDIS_AUTH_TOKEN`: random, 32+ characters, no `@`, `"` or `/`.
   - `sellerscope/METRICS_TOKEN`: random, 32+ characters.
   - `sellerscope/SMTP_PASSWORD`: the SES SMTP password.
   - `sellerscope/DATABASE_URL`: filled in at step 5.
   - `sellerscope/MIGRATION_DATABASE_URL`: filled in at step 5.
   - `sellerscope/REDIS_URL`: `rediss://:<REDIS_AUTH_TOKEN>@<redis-endpoint>:6379/0?ssl_cert_reqs=required`, filled in after apply. Celery requires `ssl_cert_reqs` on `rediss://` URLs.

   Use separate secrets for staging and production (set `secret_names` and the two `*_secret_name` variables per environment).
3. **Fill in `environments/<env>.tfvars` and `environments/<env>.backend.hcl`** (the placeholders say what). Then lock the providers for every platform you use, and commit `.terraform.lock.hcl`:
   ```bash
   terraform providers lock -platform=linux_amd64 -platform=darwin_arm64
   ```
4. **Apply:**
   ```bash
   cd infra/terraform
   terraform init -backend-config=environments/<env>.backend.hcl
   terraform plan -var-file=environments/<env>.tfvars -out=<env>.tfplan
   terraform apply <env>.tfplan
   ```
5. **Create the restricted application role** in the new database. Connect as `sellerscope_owner`, e.g. with ECS Exec or a temporary bastion; RDS isn't public. Run:
   ```sql
   CREATE ROLE sellerscope_app LOGIN PASSWORD '<random>' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
   ```
   Then set the two database secrets:
   - `DATABASE_URL` = `postgresql+asyncpg://sellerscope_app:<pw>@<db-endpoint>:5432/sellerscope?ssl=require`
   - `MIGRATION_DATABASE_URL` = the same URL, but with `sellerscope_owner`.
6. **Deploy a release** (below). After the first deploy, confirm the SNS email subscription for alarms.

## Every release
1. Tag the commit; CI must be green (tests, e2e, audits, Terraform validate).
2. **Build and push the images** with the commit SHA as the tag (tags are immutable in ECR):
   - API: `docker build -t <ecr-api>:<sha> apps/api`
   - Web: `docker build --build-arg NEXT_PUBLIC_API_URL=https://<api-host>/api/v1 --build-arg NEXT_PUBLIC_SUPABASE_URL=… --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=… -t <ecr-web>:<sha> -f apps/web/Dockerfile .`

     The web image is built **per environment**, because `NEXT_PUBLIC_*` values are compiled in.
3. **Migrate first.** Migrations are additive, and the old code keeps working:
   ```bash
   aws ecs run-task --cluster sellerscope-<env> --launch-type FARGATE \
     --task-definition <migrate_task_definition output> \
     --network-configuration 'awsvpcConfiguration={subnets=[<private subnets>],securityGroups=[<services sg>]}'
   ```
   Wait for exit code 0; the CloudWatch log group is `/sellerscope/<env>/migrate`.
4. **Roll out:** set `image_tag` and run `terraform apply`. The ECS deployment circuit breaker rolls back automatically if the new tasks fail their health checks. `beat` is replaced stop-then-start, so it never runs twice.
5. **Smoke test:**
   - `GET https://<api>/api/v1/health/ready` returns 200.
   - Sign in, open the dashboard, run one scan.
   - Check the alarms are quiet for 15 minutes.

## Rollback
- **Code:** apply the previous `image_tag`.
- **Schema:** forward fixes are preferred. Every migration has a `downgrade()`, but downgrading can lose data written since the upgrade. Restore instead if needed (see backup-restore.md).
- **Mock connector:** it can't be enabled by mistake. The API refuses to start in staging/production with `ENABLE_MOCK_CONNECTOR=true` or any other unsafe setting (see `core/config.py`, `_problems`).

## Staging
- **Same code and Terraform, smaller sizes:** a single NAT gateway, single-AZ database, one replica of each service.
- **Its own Supabase project, SES identity and secrets.**
- **No customer data in staging:** use test organizations and, once M7 is live, a sandbox or test Seller Central account.
