variable "aws_region" {
  description = "AWS region for CloudWatch dashboard widgets"
  type        = string
}

variable "name_prefix" {
  description = "Prefix used for dashboard/alarm/topic names (e.g. shortify)"
  type        = string
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}

############################
# Notification path (SNS -> Lambda -> Slack)
############################
variable "create_sns_topic" {
  description = "Whether to create an SNS topic in this module"
  type        = bool
  default     = true
}

variable "sns_topic_name" {
  description = "SNS topic name (used when create_sns_topic=true)"
  type        = string
  default     = null
}

variable "existing_sns_topic_arn" {
  description = "Existing SNS topic ARN (used when create_sns_topic=false)"
  type        = string
  default     = null
}

variable "slack_alert_lambda_arn" {
  description = "ARN of Lambda that sends alert messages to Slack"
  type        = string
}

variable "slack_alert_lambda_name" {
  description = "Function name of Lambda that sends alert messages to Slack"
  type        = string
}

############################
# API Gateway metrics/alarms
############################
variable "enable_apigw_alarms" {
  description = "Enable API Gateway alarms"
  type        = bool
  default     = true
}

variable "api_gateway_namespace" {
  description = "CloudWatch namespace for API Gateway metrics"
  type        = string
  default     = "AWS/ApiGateway"
}

variable "api_gateway_dimensions" {
  description = <<EOT
Dimensions map for API Gateway metrics.
Example for REST API: { ApiName = "my-api", Stage = "prod" }
(Confirm exact dimensions in CloudWatch Metrics console for your API type.)
EOT
  type        = map(string)
}

variable "enable_apigw_latency_alarm" {
  description = "Enable API Gateway p95 Latency alarm"
  type        = bool
  default     = true
}

variable "apigw_5xx_period_seconds" {
  type    = number
  default = 300
}

variable "apigw_5xx_evaluation_periods" {
  type    = number
  default = 1
}

variable "apigw_latency_period_seconds" {
  type    = number
  default = 300
}

variable "apigw_latency_evaluation_periods" {
  type    = number
  default = 2
}

variable "apigw_latency_datapoints_to_alarm" {
  type    = number
  default = 2
}

variable "apigw_latency_p95_threshold_ms" {
  description = "API Gateway p95 latency threshold in ms"
  type        = number
  default     = 1000
}

############################
# Lambda metrics/alarms
############################
variable "lambda_function_names" {
  description = "Map of logical key => Lambda function name (e.g. { redirect = \"...\", shorten = \"...\" })"
  type        = map(string)
  default     = {}
}

variable "lambda_error_alarm_targets" {
  description = "Lambda logical keys to create Errors alarms for. Empty = all lambda_function_names"
  type        = list(string)
  default     = []
}

variable "lambda_throttle_alarm_targets" {
  description = "Lambda logical keys to create Throttles alarms for"
  type        = list(string)
  default     = []
}

variable "lambda_duration_thresholds_ms" {
  description = "Map of logical key => Duration p95 threshold ms (creates duration alarm for keys present)"
  type        = map(number)
  default     = {}
}

variable "lambda_alarm_period_seconds" {
  type    = number
  default = 300
}

variable "lambda_error_evaluation_periods" {
  type    = number
  default = 1
}

variable "lambda_throttle_evaluation_periods" {
  type    = number
  default = 1
}

variable "lambda_duration_evaluation_periods" {
  type    = number
  default = 2
}

variable "lambda_duration_datapoints_to_alarm" {
  type    = number
  default = 2
}


############################
# Dashboard
############################
variable "create_dashboard" {
  description = "Whether to create CloudWatch dashboard"
  type        = bool
  default     = true
}

variable "dashboard_name" {
  description = "Override dashboard name (optional)"
  type        = string
  default     = null
}

variable "apigw_4xx_period_seconds" {
  type    = number
  default = 300
}

variable "apigw_4xx_evaluation_periods" {
  type    = number
  default = 1
}

variable "apigw_4xx_threshold_count" {
  type    = number
  default = 10
}

variable "eventbridge_monitoring_dashboard_enabled" {
  description = "Whether to create the EventBridge scheduled pipeline monitoring dashboard"
  type        = bool
  default     = false
}

variable "eventbridge_monitoring_dashboard_name" {
  description = "CloudWatch dashboard name for EventBridge scheduled pipeline monitoring"
  type        = string
  default     = "url-shortener-ops-eventbridge-monitoring"
}

variable "eventbridge_monitoring_rule_names" {
  description = "List of EventBridge scheduled rule names to monitor (e.g. 5m, 30m, 1h rules)"
  type        = list(string)
  default     = []
}

variable "eventbridge_monitoring_period_seconds" {
  description = "Widget period (seconds) for EventBridge monitoring dashboard"
  type        = number
  default     = 3600
}

######################################
# AI Summary Lambda subscription (optional)
######################################

variable "enable_ai_summary_subscription" {
  description = "Whether to subscribe AI summary Lambda to the same SNS ops alerts topic"
  type        = bool
  default     = false
}

variable "ai_summary_lambda_arn" {
  description = "ARN of AI summary Slack Lambda to subscribe to SNS topic"
  type        = string
  default     = null

  validation {
    condition     = var.enable_ai_summary_subscription == false || (var.ai_summary_lambda_arn != null && trimspace(var.ai_summary_lambda_arn) != "")
    error_message = "ai_summary_lambda_arn must be provided when enable_ai_summary_subscription is true."
  }
}

variable "ai_summary_lambda_name" {
  description = "Function name of AI summary Slack Lambda (for aws_lambda_permission)"
  type        = string
  default     = null

  validation {
    condition     = var.enable_ai_summary_subscription == false || (var.ai_summary_lambda_name != null && trimspace(var.ai_summary_lambda_name) != "")
    error_message = "ai_summary_lambda_name must be provided when enable_ai_summary_subscription is true."
  }
}