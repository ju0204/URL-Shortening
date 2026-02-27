locals {
  resolved_sns_topic_name = coalesce(var.sns_topic_name, "${var.name_prefix}-ops-alerts")
  dashboard_name          = coalesce(var.dashboard_name, "${var.name_prefix}-ops-monitoring")

  topic_arn = var.create_sns_topic ? aws_sns_topic.ops_alerts[0].arn : var.existing_sns_topic_arn

  # Lambda alarm target selection
  lambda_error_targets = (
    length(var.lambda_error_alarm_targets) > 0
    ? { for k in var.lambda_error_alarm_targets : k => var.lambda_function_names[k] }
    : var.lambda_function_names
  )

  lambda_throttle_targets = {
    for k in var.lambda_throttle_alarm_targets : k => var.lambda_function_names[k]
  }

  lambda_duration_targets = {
    for k, threshold in var.lambda_duration_thresholds_ms : k => {
      function_name = var.lambda_function_names[k]
      threshold_ms  = threshold
    }
    if contains(keys(var.lambda_function_names), k)
  }

  lambda_keys = sort(keys(var.lambda_function_names))


  # Alarm ARNs for dashboard alarm widget
  alarm_arns = concat(
    (var.enable_apigw_alarms ? [aws_cloudwatch_metric_alarm.apigw_5xx[0].arn] : []),
    (var.enable_apigw_alarms ? [aws_cloudwatch_metric_alarm.apigw_4xx[0].arn] : []),
    ((var.enable_apigw_alarms && var.enable_apigw_latency_alarm) ? [aws_cloudwatch_metric_alarm.apigw_latency_p95[0].arn] : []),
    [for a in aws_cloudwatch_metric_alarm.lambda_errors : a.arn],
    [for a in aws_cloudwatch_metric_alarm.lambda_throttles : a.arn],
    [for a in aws_cloudwatch_metric_alarm.lambda_duration_p95 : a.arn]
  )

  ########################################
  # Dashboard widget layout calculations
  ########################################
  lambda_overview_row_count = max(1, ceil(length(local.lambda_keys) / 2))
  lambda_duration_row_count = max(1, ceil(length(keys(local.lambda_duration_targets)) / 2))


  # Y offsets
  y_api_row1     = 0
  y_api_row2     = 6
  y_alarm_widget = 12

  y_lambda_overview_start = 16
  y_lambda_duration_start = local.y_lambda_overview_start + (local.lambda_overview_row_count * 6)


  ########################################
  # Dashboard widgets
  ########################################
  api_widgets = [
    {
      type   = "metric"
      x      = 0
      y      = local.y_api_row1
      width  = 12
      height = 6
      properties = {
        title  = "API Gateway - Count / 4XX / 5XX"
        view   = "timeSeries"
        region = var.aws_region
        stat   = "Sum"
        period = var.apigw_5xx_period_seconds
        metrics = [
          [var.api_gateway_namespace, "Count", "ApiId", var.api_gateway_dimensions["ApiId"], "Stage", var.api_gateway_dimensions["Stage"]],
          [".", "4xx", ".", ".", ".", "."],
          [".", "5xx", ".", ".", ".", "."]
        ]
      }
    },
    {
      type   = "metric"
      x      = 12
      y      = local.y_api_row1
      width  = 12
      height = 6
      properties = {
        title  = "API Gateway - Latency / IntegrationLatency (p95)"
        view   = "timeSeries"
        region = var.aws_region
        period = var.apigw_latency_period_seconds
        stat   = "p95"
        metrics = [
          [var.api_gateway_namespace, "Latency", "ApiId", var.api_gateway_dimensions["ApiId"], "Stage", var.api_gateway_dimensions["Stage"]],
          [".", "IntegrationLatency", ".", ".", ".", "."]
        ]
      }
    }
  ]

  alarm_widget = (
    length(local.alarm_arns) > 0
    ? [
      {
        type   = "alarm"
        x      = 0
        y      = local.y_alarm_widget
        width  = 24
        height = 4
        properties = {
          title  = "Alarm Status"
          alarms = local.alarm_arns
        }
      }
    ]
    : []
  )

  lambda_overview_widgets = [
    for idx, key in local.lambda_keys : {
      type   = "metric"
      x      = (idx % 2) * 12
      y      = local.y_lambda_overview_start + (floor(idx / 2) * 6)
      width  = 12
      height = 6
      properties = {
        title  = "Lambda-${key} - Invocations / Errors / Throttles"
        view   = "timeSeries"
        region = var.aws_region
        stat   = "Sum"
        period = var.lambda_alarm_period_seconds
        metrics = [
          ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function_names[key]],
          [".", "Errors", ".", "."],
          [".", "Throttles", ".", "."]
        ]
      }
    }
  ]

  lambda_duration_keys = sort(keys(local.lambda_duration_targets))

  lambda_duration_widgets = [
    for idx, key in local.lambda_duration_keys : {
      type   = "metric"
      x      = (idx % 2) * 12
      y      = local.y_lambda_duration_start + (floor(idx / 2) * 6)
      width  = 12
      height = 6
      properties = {
        title  = "Lambda-${key} - Duration p95"
        view   = "timeSeries"
        region = var.aws_region
        stat   = "p95"
        period = var.lambda_alarm_period_seconds
        metrics = [
          ["AWS/Lambda", "Duration", "FunctionName", local.lambda_duration_targets[key].function_name]
        ]
        annotations = {
          horizontal = [
            {
              label = "Threshold ${local.lambda_duration_targets[key].threshold_ms}ms"
              value = local.lambda_duration_targets[key].threshold_ms
            }
          ]
        }
      }
    }
  ]


  dashboard_widgets = concat(
    local.api_widgets,
    local.alarm_widget,
    local.lambda_overview_widgets,
    local.lambda_duration_widgets
  )
}

######################################
# SNS Topic (optional)
######################################
resource "aws_sns_topic" "ops_alerts" {
  count = var.create_sns_topic ? 1 : 0

  name = local.resolved_sns_topic_name
  tags = var.tags
}

######################################
# SNS -> Lambda subscription (Slack sender Lambda)
######################################
resource "aws_sns_topic_subscription" "slack_lambda" {
  topic_arn = local.topic_arn
  protocol  = "lambda"
  endpoint  = var.slack_alert_lambda_arn
}

resource "aws_lambda_permission" "allow_sns_invoke_alert_lambda" {
  statement_id  = "AllowExecutionFromSNS-${replace(local.resolved_sns_topic_name, "-", "")}"
  action        = "lambda:InvokeFunction"
  function_name = var.slack_alert_lambda_name
  principal     = "sns.amazonaws.com"
  source_arn    = local.topic_arn
}

######################################
# API Gateway alarms
######################################
resource "aws_cloudwatch_metric_alarm" "apigw_5xx" {
  count = var.enable_apigw_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-apigw-5xx-error"
  alarm_description   = "API Gateway 5XXError > 0"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.apigw_5xx_evaluation_periods
  period              = var.apigw_5xx_period_seconds
  threshold           = 0
  statistic           = "Sum"
  namespace           = var.api_gateway_namespace
  metric_name         = "5xx"
  dimensions          = var.api_gateway_dimensions

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]

  treat_missing_data = "notBreaching"
  tags               = var.tags
}

resource "aws_cloudwatch_metric_alarm" "apigw_4xx" {
  count = var.enable_apigw_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-apigw-4xx-error"
  alarm_description   = "API Gateway 4XXError > 0"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.apigw_4xx_evaluation_periods
  period              = var.apigw_4xx_period_seconds
  threshold           = 0
  statistic           = "Sum"
  namespace           = var.api_gateway_namespace
  metric_name         = "4xx"
  dimensions          = var.api_gateway_dimensions

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]

  treat_missing_data = "notBreaching"
  tags               = var.tags
}

resource "aws_cloudwatch_metric_alarm" "apigw_latency_p95" {
  count = (var.enable_apigw_alarms && var.enable_apigw_latency_alarm) ? 1 : 0

  alarm_name          = "${var.name_prefix}-apigw-latency-p95-high"
  alarm_description   = "API Gateway p95 Latency > ${var.apigw_latency_p95_threshold_ms} ms"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.apigw_latency_evaluation_periods
  datapoints_to_alarm = var.apigw_latency_datapoints_to_alarm
  period              = var.apigw_latency_period_seconds
  threshold           = var.apigw_latency_p95_threshold_ms
  extended_statistic  = "p95"
  namespace           = var.api_gateway_namespace
  metric_name         = "Latency"
  dimensions          = var.api_gateway_dimensions

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]

  treat_missing_data = "notBreaching"
  tags               = var.tags
}

######################################
# Lambda alarms (function-level)
######################################
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.lambda_error_targets

  alarm_name          = "${var.name_prefix}-lambda-${each.key}-errors"
  alarm_description   = "Lambda ${each.key} Errors > 0"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.lambda_error_evaluation_periods
  period              = var.lambda_alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]

  treat_missing_data = "notBreaching"
  tags               = var.tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each = local.lambda_throttle_targets

  alarm_name          = "${var.name_prefix}-lambda-${each.key}-throttles"
  alarm_description   = "Lambda ${each.key} Throttles > 0"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.lambda_throttle_evaluation_periods
  period              = var.lambda_alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]

  treat_missing_data = "notBreaching"
  tags               = var.tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration_p95" {
  for_each = local.lambda_duration_targets

  alarm_name          = "${var.name_prefix}-lambda-${each.key}-duration-p95-high"
  alarm_description   = "Lambda ${each.key} p95 Duration > ${each.value.threshold_ms} ms"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.lambda_duration_evaluation_periods
  datapoints_to_alarm = var.lambda_duration_datapoints_to_alarm
  period              = var.lambda_alarm_period_seconds
  threshold           = each.value.threshold_ms
  extended_statistic  = "p95"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"

  dimensions = {
    FunctionName = each.value.function_name
  }

  alarm_actions = [local.topic_arn]
  ok_actions    = [local.topic_arn]

  treat_missing_data = "notBreaching"
  tags               = var.tags
}


######################################
# CloudWatch Dashboard
######################################
resource "aws_cloudwatch_dashboard" "ops" {
  count = var.create_dashboard ? 1 : 0

  dashboard_name = local.dashboard_name
  dashboard_body = jsonencode({
    widgets = local.dashboard_widgets
  })
}

#===============Eventbridge ==============
locals {
  eventbridge_triggered_rules_metrics = [
    for rule_name in var.eventbridge_monitoring_rule_names : [
      "AWS/Events", "TriggeredRules", "RuleName", rule_name,
      {
        stat  = "Sum"
        label = "${rule_name} - TriggeredRules"
      }
    ]
  ]

  eventbridge_invocations_metrics = [
    for rule_name in var.eventbridge_monitoring_rule_names : [
      "AWS/Events", "Invocations", "RuleName", rule_name,
      {
        stat  = "Sum"
        label = "${rule_name} - Invocations"
      }
    ]
  ]

  eventbridge_failed_invocations_metrics = [
    for rule_name in var.eventbridge_monitoring_rule_names : [
      "AWS/Events", "FailedInvocations", "RuleName", rule_name,
      {
        stat  = "Sum"
        label = "${rule_name} - FailedInvocations"
      }
    ]
  ]
}

resource "aws_cloudwatch_dashboard" "eventbridge_monitoring" {
  count = var.eventbridge_monitoring_dashboard_enabled ? 1 : 0

  dashboard_name = var.eventbridge_monitoring_dashboard_name

  dashboard_body = jsonencode({
    widgets = [
      # 1) TriggeredRules (규칙 3개 함께)
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 24
        height = 6
        properties = {
          title   = "EventBridge TriggeredRules (Scheduled Rules)"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          period  = var.eventbridge_monitoring_period_seconds
          stat    = "Sum"
          metrics = local.eventbridge_triggered_rules_metrics
        }
      },

      # 2) Invocations (규칙 3개 함께)
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 24
        height = 6
        properties = {
          title   = "EventBridge Invocations (Target Calls)"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          period  = var.eventbridge_monitoring_period_seconds
          stat    = "Sum"
          metrics = local.eventbridge_invocations_metrics
        }
      },

      # 3) FailedInvocations (규칙 3개 함께)
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title   = "EventBridge FailedInvocations"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          period  = var.eventbridge_monitoring_period_seconds
          stat    = "Sum"
          metrics = local.eventbridge_failed_invocations_metrics
        }
      }
    ]
  })
}

######################################
# SNS -> Lambda subscription (AI summary Lambda) [optional]
######################################
resource "aws_sns_topic_subscription" "ai_summary_lambda" {
  count = var.enable_ai_summary_subscription ? 1 : 0

  topic_arn = local.topic_arn
  protocol  = "lambda"
  endpoint  = var.ai_summary_lambda_arn
}

resource "aws_lambda_permission" "allow_sns_invoke_ai_summary_lambda" {
  count = var.enable_ai_summary_subscription ? 1 : 0

  statement_id  = "AllowExecutionFromSNSAISummary-${replace(local.resolved_sns_topic_name, "-", "")}"
  action        = "lambda:InvokeFunction"
  function_name = var.ai_summary_lambda_name
  principal     = "sns.amazonaws.com"
  source_arn    = local.topic_arn
}