output "canary_name" {
  description = "Created canary name"
  value       = try(aws_synthetics_canary.this[0].name, null)
}

output "canary_arn" {
  description = "Created canary ARN"
  value       = try(aws_synthetics_canary.this[0].arn, null)
}

output "canary_alarm_name" {
  description = "Canary alarm name (3 consecutive failures)"
  value       = try(aws_cloudwatch_metric_alarm.canary_3fail_warn[0].alarm_name, null)
}

output "canary_dashboard_name" {
  description = "Canary dashboard name"
  value       = try(aws_cloudwatch_dashboard.canary[0].dashboard_name, null)
}

output "canary_role_arn" {
  description = "Canary execution role ARN"
  value       = try(aws_iam_role.canary[0].arn, null)
}

output "artifact_s3_bucket_name" {
  description = "S3 bucket used for canary artifacts"
  value       = local.resolved_artifact_bucket
}

output "artifact_s3_bucket_arn" {
  description = "ARN of created artifact bucket (null if using existing bucket)"
  value       = try(aws_s3_bucket.canary_artifacts[0].arn, null)
}