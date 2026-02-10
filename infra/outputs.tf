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

output "shorten_api_url" {
  value = module.apigw.shorten_url
}
