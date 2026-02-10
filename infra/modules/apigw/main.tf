resource "aws_apigatewayv2_api" "this" {
  name          = var.api_name
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Content-Type"]
    max_age       = 3600
  }

  tags = {
    Project = var.project_name
    Name    = var.api_name
  }
}

resource "aws_apigatewayv2_integration" "shorten" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.lambda_invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "shorten" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST /shorten"
  target    = "integrations/${aws_apigatewayv2_integration.shorten.id}"
}

resource "aws_apigatewayv2_stage" "this" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = var.stage_name
  auto_deploy = true

  tags = {
    Project = var.project_name
  }
}

# API Gateway가 Lambda를 호출할 수 있도록 권한 부여
resource "aws_lambda_permission" "allow_apigw_invoke" {
  statement_id  = "AllowExecutionFromHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"

  # 모든 route/method 허용(간단/안전). 필요하면 POST /shorten만으로 더 좁힐 수 있음.
  source_arn = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

# redirect lambda용
resource "aws_apigatewayv2_integration" "redirect" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.redirect_lambda_invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "redirect" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET /{shortId}"
  target    = "integrations/${aws_apigatewayv2_integration.redirect.id}"
}

resource "aws_lambda_permission" "allow_apigw_invoke_redirect" {
  statement_id  = "AllowExecutionFromHttpApiRedirect"
  action        = "lambda:InvokeFunction"
  function_name = var.redirect_lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

#커스텀 도메인 설정
# custom_domain_name이 비어있지 않을 때만 생성

data "aws_acm_certificate" "custom" {
  count       = var.custom_domain_name != "" ? 1 : 0
  domain      = var.acm_certificate_domain != "" ? var.acm_certificate_domain : var.custom_domain_name
  statuses    = ["ISSUED"]
  most_recent = true
}

resource "aws_apigatewayv2_domain_name" "custom" {
  count       = var.custom_domain_name != "" ? 1 : 0
  domain_name = var.custom_domain_name

  domain_name_configuration {
    certificate_arn = data.aws_acm_certificate.custom[0].arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

# API Mapping: base path 비워서 루트로 매핑 => https://shortify.cloud/{shortId}
resource "aws_apigatewayv2_api_mapping" "root" {
  count       = var.custom_domain_name != "" ? 1 : 0
  api_id      = aws_apigatewayv2_api.this.id
  domain_name = aws_apigatewayv2_domain_name.custom[0].id
  stage       = aws_apigatewayv2_stage.this.name

  # api_mapping_key를 지정하지 않으면 루트 매핑됨 (base path empty)
}

# Route53 Alias (A / AAAA)
resource "aws_route53_record" "apigw_a" {
  count   = (var.custom_domain_name != "" && var.hosted_zone_id != "") ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = var.custom_domain_name
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.custom[0].domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.custom[0].domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "apigw_aaaa" {
  count   = (var.custom_domain_name != "" && var.hosted_zone_id != "") ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = var.custom_domain_name
  type    = "AAAA"

  alias {
    name                   = aws_apigatewayv2_domain_name.custom[0].domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.custom[0].domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
