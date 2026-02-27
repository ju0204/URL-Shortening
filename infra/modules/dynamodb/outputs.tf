output "urls_table_name" {
  value = aws_dynamodb_table.urls.name
}

output "clicks_table_name" {
  value = aws_dynamodb_table.clicks.name
}

output "insights_table_name" {
  value = aws_dynamodb_table.insights.name
}

output "urls_table_arn" {
  value = aws_dynamodb_table.urls.arn
}

output "clicks_table_arn" {
  value = aws_dynamodb_table.clicks.arn
}

output "insights_table_arn" {
  value = aws_dynamodb_table.insights.arn
}

output "ai_table_name" {
  value = aws_dynamodb_table.ai.name
}

output "ai_table_arn" {
  value = aws_dynamodb_table.ai.arn
}
