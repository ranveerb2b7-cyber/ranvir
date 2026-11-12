resource "aws_sns_topic" "alarms" {
  name              = "${local.name}-alarms"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alarms = {
    api-5xx = {
      namespace   = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", stat = "Sum",
      threshold   = 10, comparison = "GreaterThanThreshold",
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix },
      description = "API returned more than 10 server errors in 5 minutes (runbooks/incident-response.md)"
    }
    api-latency = {
      namespace   = "AWS/ApplicationELB", metric = "TargetResponseTime", stat = "p95",
      threshold   = 1, comparison = "GreaterThanThreshold",
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix },
      description = "API p95 latency above 1 s"
    }
    api-unhealthy = {
      namespace   = "AWS/ApplicationELB", metric = "UnHealthyHostCount", stat = "Maximum",
      threshold   = 0, comparison = "GreaterThanThreshold",
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix },
      description = "An API task fails its readiness check (database or Redis unreachable)"
    }
    db-cpu = {
      namespace   = "AWS/RDS", metric = "CPUUtilization", stat = "Average",
      threshold   = 80, comparison = "GreaterThanThreshold",
      dimensions  = { DBInstanceIdentifier = aws_db_instance.main.identifier },
      description = "Database CPU above 80%"
    }
    db-storage = {
      namespace   = "AWS/RDS", metric = "FreeStorageSpace", stat = "Minimum",
      threshold   = 10 * 1024 * 1024 * 1024, comparison = "LessThanThreshold",
      dimensions  = { DBInstanceIdentifier = aws_db_instance.main.identifier },
      description = "Database free storage below 10 GB"
    }
    redis-memory = {
      namespace   = "AWS/ElastiCache", metric = "DatabaseMemoryUsagePercentage", stat = "Maximum",
      threshold   = 80, comparison = "GreaterThanThreshold",
      dimensions  = { ReplicationGroupId = aws_elasticache_replication_group.main.id },
      description = "Redis memory above 80% (queue backlog?)"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "main" {
  for_each            = local.alarms
  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = contains(["Sum", "Average", "Minimum", "Maximum"], each.value.stat) ? each.value.stat : null
  extended_statistic  = contains(["Sum", "Average", "Minimum", "Maximum"], each.value.stat) ? null : each.value.stat
  dimensions          = each.value.dimensions
  period              = 300
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}
