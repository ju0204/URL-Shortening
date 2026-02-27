terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    archive = {
      source = "hashicorp/archive"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  canary_enabled = var.enabled

  resolved_artifact_bucket = var.create_artifact_bucket ? try(aws_s3_bucket.canary_artifacts[0].id, null) : var.artifact_s3_bucket

  canary_zip_output_path = "${path.module}/.build/shortify_e2e_canary.zip"
  canary_zip_s3_key      = "${trim(var.artifact_s3_prefix, "/")}/code/${var.canary_name}.zip"

  canary_env = {
    API_BASE_URL       = var.api_base_url
    TEST_SHORTEN_URL   = var.test_shorten_url
    TEST_SHORTEN_TITLE = var.test_shorten_title
    AI_PERIOD          = var.ai_period
  }

  canary_alarm_name = "${var.canary_name}-3fail-warn"
}

resource "aws_iam_role" "canary" {
  count = local.canary_enabled ? 1 : 0

  name = "${var.canary_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = [
            "lambda.amazonaws.com",
            "synthetics.amazonaws.com"
          ]
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = var.tags
}



# 최소 권한으로 직접 줄 수도 있지만, 처음엔 안정적으로 시작하는 쪽 권장
# 필요시 이후 줄이기

resource "aws_iam_role_policy" "canary_inline_s3" {
  count = local.canary_enabled ? 1 : 0

  name = "${var.canary_name}-inline-s3"
  role = aws_iam_role.canary[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowArtifactBucketAccess"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::${local.resolved_artifact_bucket}",
          "arn:aws:s3:::${local.resolved_artifact_bucket}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "canary_inline_cloudwatch_metrics" {
  count = local.canary_enabled ? 1 : 0

  name = "${var.canary_name}-inline-cw-metrics"
  role = aws_iam_role.canary[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowPutMetricDataForSynthetics"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "CloudWatchSynthetics"
          }
        }
      }
    ]
  })
}


resource "aws_s3_object" "canary_script_zip" {
  count = local.canary_enabled ? 1 : 0

  bucket = local.resolved_artifact_bucket
  key    = local.canary_zip_s3_key
  source = data.archive_file.canary_zip[0].output_path
  etag   = filemd5(data.archive_file.canary_zip[0].output_path)

  depends_on = [
    aws_iam_role_policy.canary_inline_s3,
    aws_iam_role_policy.canary_inline_cloudwatch_metrics,
    aws_iam_role_policy.canary_inline_logs
  ]
}

resource "aws_synthetics_canary" "this" {
  count = local.canary_enabled ? 1 : 0

  name                 = var.canary_name
  artifact_s3_location = "s3://${local.resolved_artifact_bucket}/${trim(var.artifact_s3_prefix, "/")}/artifacts/"
  execution_role_arn   = aws_iam_role.canary[0].arn
  handler              = "shortify_e2e_canary.handler"
  runtime_version      = var.canary_runtime_version
  start_canary         = true

  s3_bucket = local.resolved_artifact_bucket
  s3_key    = aws_s3_object.canary_script_zip[0].key

  schedule {
    expression = var.canary_schedule_expression
  }

  run_config {
    timeout_in_seconds    = var.canary_timeout_in_seconds
    memory_in_mb          = var.canary_memory_in_mb
    active_tracing        = false
    environment_variables = local.canary_env
  }

  success_retention_period = 31
  failure_retention_period = 31

  depends_on = [
    aws_iam_role_policy.canary_inline_s3,
    aws_iam_role_policy.canary_inline_cloudwatch_metrics,
    aws_iam_role_policy.canary_inline_logs,
    aws_s3_object.canary_script_zip
  ]

  tags = var.tags
}

# canary 스크립트 zip 생성
data "archive_file" "canary_zip" {
  count = local.canary_enabled ? 1 : 0

  type        = "zip"
  output_path = local.canary_zip_output_path

  source {
    content  = file("${path.module}/scripts/shortify_e2e_canary.js")
    filename = "shortify_e2e_canary.js"
  }
}

resource "aws_iam_role_policy" "canary_inline_logs" {
  count = local.canary_enabled ? 1 : 0

  name = "${var.canary_name}-inline-logs"
  role = aws_iam_role.canary[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudWatchLogsForCanaryLambda"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Resource = "*"
      }
    ]
  })
}

# 연속 3회 실패 경고 알람 (SuccessPercent < 100 이 3/3)
resource "aws_cloudwatch_metric_alarm" "canary_3fail_warn" {
  count = local.canary_enabled ? 1 : 0

  alarm_name          = local.canary_alarm_name
  alarm_description   = "Warn when canary fails 3 consecutive runs (SuccessPercent < 100)"
  comparison_operator = "LessThanThreshold"
  threshold           = 100
  evaluation_periods  = var.alarm_evaluation_periods
  datapoints_to_alarm = var.alarm_datapoints_to_alarm
  period              = var.alarm_period_seconds
  statistic           = "Average"
  treat_missing_data  = "notBreaching"

  namespace   = "CloudWatchSynthetics"
  metric_name = "SuccessPercent"

  dimensions = {
    CanaryName = var.canary_name
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.ok_actions

  tags = var.tags
}

resource "aws_s3_bucket" "canary_artifacts" {
  count = local.canary_enabled && var.create_artifact_bucket ? 1 : 0

  bucket = var.artifact_s3_bucket_name

  tags = merge(var.tags, {
    Name = var.artifact_s3_bucket_name
    Role = "monitoring-canary-artifacts"
  })
}

resource "aws_s3_bucket_public_access_block" "canary_artifacts" {
  count = local.canary_enabled && var.create_artifact_bucket ? 1 : 0

  bucket = aws_s3_bucket.canary_artifacts[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "canary_artifacts" {
  count = local.canary_enabled && var.create_artifact_bucket ? 1 : 0

  bucket = aws_s3_bucket.canary_artifacts[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 선택: 버킷 버전닝 (처음엔 꺼도 됨)
# resource "aws_s3_bucket_versioning" "canary_artifacts" {
#   count  = local.canary_enabled && var.create_artifact_bucket ? 1 : 0
#   bucket = aws_s3_bucket.canary_artifacts[0].id
#   versioning_configuration {
#     status = "Enabled"
#   }
# }

resource "aws_cloudwatch_dashboard" "canary" {
  count = local.canary_enabled ? 1 : 0

  dashboard_name = var.dashboard_name

  dashboard_body = jsonencode({
    widgets = [
      # Alarm status widget
      {
        type   = "alarm"
        x      = 0
        y      = 0
        width  = 24
        height = 6
        properties = {
          alarms = [
            aws_cloudwatch_metric_alarm.canary_3fail_warn[0].arn
          ]
          title = "Canary Alarm Status"
        }
      },

      # SuccessPercent
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Canary SuccessPercent"
          region  = data.aws_region.current.name
          stat    = "Average"
          period  = var.alarm_period_seconds
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["CloudWatchSynthetics", "SuccessPercent", "CanaryName", var.canary_name]
          ]
          yAxis = {
            left = {
              min = 0
              max = 100
            }
          }
        }
      },

      # Duration
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Canary Duration (ms)"
          region  = data.aws_region.current.name
          stat    = "Average"
          period  = var.alarm_period_seconds
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["CloudWatchSynthetics", "Duration", "CanaryName", var.canary_name]
          ]
        }
      },

      # Failed count
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title   = "Canary Failed"
          region  = data.aws_region.current.name
          stat    = "Sum"
          period  = var.alarm_period_seconds
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["CloudWatchSynthetics", "Failed", "CanaryName", var.canary_name]
          ]
        }
      },

      # Runs
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          title   = "Canary Runs"
          region  = data.aws_region.current.name
          stat    = "SampleCount"
          period  = var.alarm_period_seconds
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["CloudWatchSynthetics", "SuccessPercent", "CanaryName", var.canary_name]
          ]
        }
      }
    ]
  })
}