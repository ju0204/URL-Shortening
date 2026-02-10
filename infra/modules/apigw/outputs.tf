output "api_endpoint" {
  value = aws_apigatewayv2_api.this.api_endpoint
}

output "stage_name" {
  value = aws_apigatewayv2_stage.this.name
}

output "shorten_url" {
  value = "${aws_apigatewayv2_api.this.api_endpoint}/${aws_apigatewayv2_stage.this.name}/shorten"
}

#커스텀 도메인 설정
output "custom_domain_url" {
  value       = var.custom_domain_name != "" ? "https://${var.custom_domain_name}" : null
  description = "Custom domain base URL."
}

output "execute_api_base_url" {
  value       = aws_apigatewayv2_stage.this.invoke_url
  description = "Default execute-api base URL (stage invoke url)."
}
