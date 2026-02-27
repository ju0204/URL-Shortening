output "urls_table_name" {
  value = module.dynamodb.urls_table_name
}

output "clicks_table_name" {
  value = module.dynamodb.clicks_table_name
}

output "insights_table_name" {
  value = module.dynamodb.insights_table_name
}

output "lambda_role_arn" {
  value = module.iam.lambda_role_arn
}

output "base_url" {
  value = module.apigw.base_url
}

output "shorten_api_url" {
  value = "${module.apigw.base_url}/shorten"
}

output "stats_api_url" {
  value = "${module.apigw.base_url}/stats"
}

output "frontend_bucket_name" {
  value = module.frontend.bucket_name
}

output "cloudfront_distribution_id" {
  value = module.frontend.distribution_id
}

output "github_deploy_role_arn" {
  value = module.oidc.role_arn
}

output "grafana_athena_role_arn" {
  value = module.monitoring.grafana_athena_role_arn
}