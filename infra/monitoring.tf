# Alarms, emailed through SNS: a failed ETL run, API errors, and the database filling up.

resource "aws_sns_topic" "alarms" {
  name = "${var.project}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# `atlas sync` logs "Traceback" when a run fails (and records it in atlas_meta.sync_runs).
resource "aws_cloudwatch_log_metric_filter" "etl_failed" {
  name           = "${var.project}-etl-failed"
  log_group_name = aws_cloudwatch_log_group.etl.name
  pattern        = "?Traceback ?\"sync failed\" ?FAILED"
  metric_transformation {
    name      = "EtlFailures"
    namespace = var.project
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "etl_failed" {
  alarm_name          = "${var.project}-etl-failed"
  alarm_description   = "An ETL run failed; see the /${var.project}/etl logs."
  namespace           = var.project
  metric_name         = "EtlFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.project}-api-5xx"
  alarm_description   = "The API is returning server errors."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${var.project}-db-storage-low"
  alarm_description   = "Postgres has under 2 GB free."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2 * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
