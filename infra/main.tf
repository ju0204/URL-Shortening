terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}


module "dynamodb" {
  source             = "./modules/dynamodb"
  project_name       = var.project_name
  urls_ttl_attribute = "expiresAt"
}

module "iam" {
  source       = "./modules/iam"
  project_name = var.project_name

  urls_table_arn     = module.dynamodb.urls_table_arn
  clicks_table_arn   = module.dynamodb.clicks_table_arn
  insights_table_arn = module.dynamodb.insights_table_arn
}

module "lambda_shorten" {
  source = "./modules/lambda"

  project_name = var.project_name
  function_name = "${var.project_name}-shorten"
  role_arn      = module.iam.lambda_role_arn

  # 코드 위치: repo-root/lambda/shorten/handler.py
  source_dir    = "${path.module}/../lambda/shorten"
  handler       = "handler.lambda_handler"
  runtime       = "python3.11"

  environment = {
    URLS_TABLE            = module.dynamodb.urls_table_name
    BASE_URL              = "https://shortify.cloud"
    SHORT_ID_LEN          = "8"
    MAX_RETRIES           = "5"
    TITLE_FETCH_TIMEOUT   = "2.5"
    MAX_HTML_BYTES        = "262144"
  }
}
 

module "lambda_redirect" {
  source        = "./modules/lambda"

  project_name  = var.project_name
  function_name = "${var.project_name}-redirect"
  role_arn      = module.iam.lambda_role_arn

  source_dir = "${path.module}/../lambda/redirect"
  handler    = "handler.lambda_handler"
  runtime    = "python3.11"

  timeout     = 10
  memory_size = 128

  environment = {
    URLS_TABLE     = module.dynamodb.urls_table_name
    CLICKS_TABLE   = module.dynamodb.clicks_table_name
    REDIRECT_STATUS = "301"
  }
}


module "apigw" {
  source = "./modules/apigw"

  project_name         = var.project_name
  api_name             = "${var.project_name}-http-api"
  stage_name           = "prod"

  lambda_invoke_arn     = module.lambda_shorten.invoke_arn
  lambda_function_name  = module.lambda_shorten.lambda_function_name

  # redirect lambda용
  redirect_lambda_invoke_arn    = module.lambda_redirect.invoke_arn
  redirect_lambda_function_name = module.lambda_redirect.lambda_function_name

  #커스텀도메인 설정
  custom_domain_name      = "shortify.cloud"
  hosted_zone_id          = data.aws_route53_zone.shortify.zone_id
  acm_certificate_domain  = "shortify.cloud"

}

data "aws_route53_zone" "shortify" {
  name         = "shortify.cloud."
  private_zone = false
}

