output "sns_topic_arn" {
  value = local.topic_arn
}

output "dashboard_name" {
  value = var.create_dashboard ? aws_cloudwatch_dashboard.ops[0].dashboard_name : null
}

output "eventbridge_monitoring_dashboard_name" {
  description = "EventBridge monitoring dashboard name"
  value = (
    var.eventbridge_monitoring_dashboard_enabled
    ? aws_cloudwatch_dashboard.eventbridge_monitoring[0].dashboard_name
    : null
  )
}

output "ops_alerts_sns_topic_arn" {
  description = "SNS topic ARN used for ops alerts"
  value       = local.topic_arn
}

output "ai_summary_lambda_subscription_arn" {
  description = "SNS subscription ARN for AI summary Lambda (if enabled)"
  value       = try(aws_sns_topic_subscription.ai_summary_lambda[0].arn, null)
}