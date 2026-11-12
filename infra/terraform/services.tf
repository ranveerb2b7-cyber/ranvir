# ---------------------------------------------------------------- images, secrets, IAM

resource "aws_ecr_repository" "app" {
  for_each             = toset(["api", "web"])
  name                 = "${local.name}-${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
}

data "aws_secretsmanager_secret" "app" {
  for_each = var.secret_names
  name     = each.value
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Pulls images, writes logs and reads the listed secrets (at container start only).
resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [for s in data.aws_secretsmanager_secret.app : s.arn]
    }]
  })
}

# What the application itself may do: only its own bucket, with the project key.
resource "aws_iam_role" "task" {
  name               = "${local.name}-app"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.files.arn}/org/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.main.arn
      },
    ]
  })
}

# ---------------------------------------------------------------- tasks and services

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  for_each          = toset(["api", "worker", "beat", "web", "migrate"])
  name              = "/sellerscope/${var.environment}/${each.key}"
  retention_in_days = var.environment == "production" ? 180 : 30 # CERT-In: 180 days
}

locals {
  api_image = "${aws_ecr_repository.app["api"].repository_url}:${var.image_tag}"
  web_image = "${aws_ecr_repository.app["web"].repository_url}:${var.image_tag}"
  app_environment = merge(
    {
      APP_ENV         = var.environment
      LOG_LEVEL       = "INFO"
      RELEASE         = var.image_tag
      APP_DB_ROLE     = "sellerscope_app"
      STORAGE_BACKEND = "s3"
      S3_BUCKET       = aws_s3_bucket.files.bucket
      S3_REGION       = var.region
      WEB_BASE_URL    = "https://${var.app_hostname}"
      CORS_ORIGINS    = "https://${var.app_hostname}"
      SMTP_STARTTLS   = "true"
    },
    var.app_config,
  )
  env_list    = [for k, v in local.app_environment : { name = k, value = v }]
  secret_list = [for k, s in data.aws_secretsmanager_secret.app : { name = k, valueFrom = s.arn }]
  backend = {
    api     = { command = null, port = 8000 }
    worker  = { command = ["celery", "-A", "sellerscope.workers.celery_app", "worker", "-Q", "default,imports,scans.amazon,reports,alerts", "--loglevel=INFO"], port = null }
    beat    = { command = ["celery", "-A", "sellerscope.workers.celery_app", "beat", "--loglevel=INFO", "--schedule", "/tmp/celerybeat-schedule"], port = null }
    migrate = { command = ["alembic", "upgrade", "head"], port = null }
  }
}

resource "aws_ecs_task_definition" "backend" {
  for_each                 = local.backend
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name                   = each.key
    image                  = local.api_image
    essential              = true
    command                = each.value.command
    readonlyRootFilesystem = false
    environment            = local.env_list
    secrets                = local.secret_list
    portMappings           = each.value.port == null ? [] : [{ containerPort = each.value.port }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app[each.key].name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }])
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name         = "web"
    image        = local.web_image # NEXT_PUBLIC_* are baked in at build time (runbook)
    essential    = true
    portMappings = [{ containerPort = 3000 }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app["web"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

locals {
  services = {
    api    = { task = aws_ecs_task_definition.backend["api"].arn, count = var.api_desired_count, tg = aws_lb_target_group.api.arn, port = 8000 }
    worker = { task = aws_ecs_task_definition.backend["worker"].arn, count = var.worker_desired_count, tg = null, port = null }
    beat   = { task = aws_ecs_task_definition.backend["beat"].arn, count = 1, tg = null, port = null } # exactly one scheduler
    web    = { task = aws_ecs_task_definition.web.arn, count = var.web_desired_count, tg = aws_lb_target_group.web.arn, port = 3000 }
  }
}

resource "aws_ecs_service" "app" {
  for_each               = local.services
  name                   = each.key
  cluster                = aws_ecs_cluster.main.id
  task_definition        = each.value.task
  desired_count          = each.value.count
  launch_type            = "FARGATE"
  enable_execute_command = false
  # beat must never run twice (duplicate schedules): stop the old task before starting a new one.
  deployment_minimum_healthy_percent = each.key == "beat" ? 0 : 100
  deployment_maximum_percent         = each.key == "beat" ? 100 : 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.services.id]
    assign_public_ip = false
  }
  dynamic "load_balancer" {
    for_each = each.value.tg == null ? [] : [each.value]
    content {
      target_group_arn = load_balancer.value.tg
      container_name   = each.key
      container_port   = load_balancer.value.port
    }
  }
  depends_on = [aws_lb_listener.https]
}

# ---------------------------------------------------------------- load balancer, TLS, DNS

data "aws_route53_zone" "main" {
  name = var.route53_zone_name
}

resource "aws_acm_certificate" "main" {
  domain_name               = var.app_hostname
  subject_alternative_names = [var.api_hostname]
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for o in aws_acm_certificate.main.domain_validation_options : o.domain_name => o
  }
  zone_id = data.aws_route53_zone.main.zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}

resource "aws_lb" "main" {
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = var.environment == "production"
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/api/v1/health/ready"
    matcher = "200"
  }
}

resource "aws_lb_target_group" "web" {
  name        = "${local.name}-web"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/login"
    matcher = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.main.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

# /metrics is scraped from inside the VPC only (it also requires METRICS_TOKEN).
resource "aws_lb_listener_rule" "block_metrics" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 5
  action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      status_code  = "404"
    }
  }
  condition {
    path_pattern {
      values = ["/metrics", "/metrics/*"]
    }
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    host_header {
      values = [var.api_hostname]
    }
  }
}

resource "aws_route53_record" "hosts" {
  for_each = toset([var.app_hostname, var.api_hostname])
  zone_id  = data.aws_route53_zone.main.zone_id
  name     = each.value
  type     = "A"
  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
