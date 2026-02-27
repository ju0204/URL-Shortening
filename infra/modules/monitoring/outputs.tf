output "analytics_bucket_name" {
  value = aws_s3_bucket.analytics.bucket
}

output "athena_workgroup_name" {
  value = aws_athena_workgroup.shortify.name
}

output "glue_database_name" {
  value = aws_glue_catalog_database.shortify.name
}

output "fact_clicks_table_name" {
  value = aws_glue_catalog_table.fact_clicks.name
}

output "grafana_athena_role_arn" {
  value = aws_iam_role.grafana_athena_role.arn
}