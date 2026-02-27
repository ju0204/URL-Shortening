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

provider "aws" {
  alias  = "use1"
  region = "us-east-1"
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
  ai_table_arn       = module.dynamodb.ai_table_arn

  enable_bedrock     = true
  bedrock_model_arns = ["*"] # 나중에 모델 ARN으로 좁혀도 됨

  enable_ai_summary_bedrock = true
}

module "lambda_shorten" {
  source = "./modules/lambda"

  project_name  = var.project_name
  function_name = "${var.project_name}-shorten"
  role_arn      = module.iam.lambda_role_arn

  # 코드 위치: repo-root/lambda/shorten/handler.py
  source_dir = "${path.module}/../lambda/shorten"
  handler    = "handler.lambda_handler"
  runtime    = "python3.11"

  environment = {
    URLS_TABLE          = module.dynamodb.urls_table_name
    BASE_URL            = "https://shortify.cloud"
    SHORT_ID_LEN        = "8"
    MAX_RETRIES         = "5"
    TITLE_FETCH_TIMEOUT = "2.5"
    MAX_HTML_BYTES      = "262144"
  }
}




module "lambda_redirect" {
  source = "./modules/lambda"

  project_name  = var.project_name
  function_name = "${var.project_name}-redirect"
  role_arn      = module.iam.lambda_role_arn

  source_dir = "${path.module}/../lambda/redirect"
  handler    = "handler.lambda_handler"
  runtime    = "python3.11"

  timeout     = 10
  memory_size = 128

  environment = {
    URLS_TABLE      = module.dynamodb.urls_table_name
    CLICKS_TABLE    = module.dynamodb.clicks_table_name
    REDIRECT_STATUS = "301"
  }
}


module "apigw" {
  source = "./modules/apigw"

  project_name = var.project_name
  api_name     = "${var.project_name}-http-api"
  stage_name   = "prod"

  lambda_invoke_arn    = module.lambda_shorten.invoke_arn
  lambda_function_name = module.lambda_shorten.lambda_function_name

  # redirect lambda용
  redirect_lambda_invoke_arn    = module.lambda_redirect.invoke_arn
  redirect_lambda_function_name = module.lambda_redirect.lambda_function_name

  #커스텀도메인 설정
  custom_domain_name     = "api.shortify.cloud"
  acm_certificate_domain = "shortify.cloud"
  hosted_zone_id         = data.aws_route53_zone.shortify.zone_id

  #stats lambda용
  stats_lambda_invoke_arn    = module.lambda_stats.invoke_arn
  stats_lambda_function_name = module.lambda_stats.lambda_function_name

  #ai 호출용
  analyze_lambda_invoke_arn    = module.lambda_analyze.invoke_arn
  analyze_lambda_function_name = module.lambda_analyze.lambda_function_name
}

data "aws_route53_zone" "shortify" {
  name         = "shortify.cloud."
  private_zone = false
}

#stats lambda용
module "lambda_stats" {
  source = "./modules/lambda"

  project_name  = var.project_name
  function_name = "${var.project_name}-stats"
  role_arn      = module.iam.lambda_role_arn

  source_dir = "${path.module}/../lambda/stats"
  handler    = "handler.lambda_handler"
  runtime    = "python3.11"

  timeout     = 30
  memory_size = 256

  environment = {
    URLS_TABLE   = module.dynamodb.urls_table_name
    CLICKS_TABLE = module.dynamodb.clicks_table_name
  }
}

# analyze lambda용
module "lambda_analyze" {
  source = "./modules/analyze_lambda"

  project_name  = var.project_name
  function_name = "${var.project_name}-analyze"
  role_arn      = module.iam.lambda_role_arn

  source_dir = "${path.module}/../lambda/analyze"
  handler    = "handler.lambda_handler"
  runtime    = "python3.11"

  timeout     = 60
  memory_size = 512

  environment = {
    URLS_TABLE     = module.dynamodb.urls_table_name
    CLICKS_TABLE   = module.dynamodb.clicks_table_name
    INSIGHTS_TABLE = module.dynamodb.insights_table_name
    AI_TABLE       = module.dynamodb.ai_table_name

    # Bedrock 호출용 (리전/모델 등)
    BEDROCK_MODEL_TREND   = "apac.amazon.nova-micro-v1:0"
    BEDROCK_MODEL_INSIGHT = "apac.amazon.nova-lite-v1:0"
    ANALYTICS_BUCKET      = module.monitoring.analytics_bucket_name
    ANALYTICS_PREFIX      = "analytics"
    EXPORT_ENABLED        = "true"
    EXPORT_CHECKPOINT_KEY = "analytics/state/last_export_ts.json"
  }
}

# =========================
# EventBridge -> analyze lambda
# (handler.py 기준: job == "ai_only" 일 때만 AI 실행)
# =========================

resource "aws_cloudwatch_event_rule" "analyze_agg_5m" {
  name                = "${var.project_name}-analyze-agg-5m"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "analyze_agg_5m" {
  rule      = aws_cloudwatch_event_rule.analyze_agg_5m.name
  target_id = "analyzeAgg5m"
  arn       = module.lambda_analyze.arn

  input = jsonencode({
    job       = "aggregate_only"
    periodKey = "P#1H"
  })
}

resource "aws_cloudwatch_event_rule" "analyze_ai_30m" {
  name                = "${var.project_name}-analyze-ai-30m"
  schedule_expression = "rate(30 minutes)"
}

resource "aws_cloudwatch_event_target" "analyze_ai_30m" {
  rule      = aws_cloudwatch_event_rule.analyze_ai_30m.name
  target_id = "analyzeAi30m"
  arn       = module.lambda_analyze.arn

  # ✅ handler.py의 ai_only 분기와 맞춤
  input = jsonencode({
    job             = "ai_only"
    aiPeriodKey     = "P#30MIN"
    sourcePeriodKey = "P#24H"
  })
}

resource "aws_lambda_permission" "allow_eventbridge_analyze_agg" {
  statement_id  = "AllowEventBridgeInvokeAnalyzeAgg"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_analyze.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.analyze_agg_5m.arn
}

resource "aws_lambda_permission" "allow_eventbridge_analyze_ai" {
  statement_id  = "AllowEventBridgeInvokeAnalyzeAi"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_analyze.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.analyze_ai_30m.arn
}

# =========================
# Aggregation: P#24H (30분마다)
# =========================
resource "aws_cloudwatch_event_rule" "analyze_agg_24h_30m" {
  name                = "${var.project_name}-analyze-agg-24h-30m"
  schedule_expression = "rate(30 minutes)"
}

resource "aws_cloudwatch_event_target" "analyze_agg_24h_30m" {
  rule      = aws_cloudwatch_event_rule.analyze_agg_24h_30m.name
  target_id = "analyzeAgg24h30m"
  arn       = module.lambda_analyze.arn

  input = jsonencode({
    job       = "aggregate_only"
    periodKey = "P#24H"
  })
}

resource "aws_lambda_permission" "allow_eventbridge_analyze_agg_24h_30m" {
  statement_id  = "AllowEventBridgeInvokeAnalyzeAgg24h30m"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_analyze.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.analyze_agg_24h_30m.arn
}


#========================
# frontend 
#========================
module "acm_cloudfront" {
  source = "./modules/acm_cloudfront"
  providers = {
    aws = aws.use1
  }

  domain_name               = "shortify.cloud"
  hosted_zone_id            = data.aws_route53_zone.shortify.zone_id
  subject_alternative_names = [] # www 안 쓸거면 제거
}

module "frontend" {
  source = "./modules/frontend"

  project_name   = var.project_name
  domain_name    = "shortify.cloud"
  hosted_zone_id = data.aws_route53_zone.shortify.zone_id
  acm_cert_arn   = module.acm_cloudfront.certificate_arn

  enable_www      = false
  www_domain_name = ""

  bucket_name = "shortify-cloud-frontend-jh"
}

module "oidc" {
  source = "./modules/oidc"

  project_name  = var.project_name
  github_owner  = "ju0204"
  github_repo   = "URL-Shortening-frontend"
  github_branch = "main"

  s3_bucket_arn       = module.frontend.bucket_arn
  cloudfront_dist_arn = module.frontend.distribution_arn
}


# 모니터링----------------------
module "monitoring" {
  source = "./modules/monitoring"

  region       = var.aws_region
  project_name = var.project_name

  analytics_bucket_name = "shortify-cloud-analyze-jh"
  analytics_prefix      = "analytics"
  athena_results_prefix = "analytics/athena-results"

  analyze_lambda_role_arn  = module.iam.lambda_role_arn
  analyze_lambda_role_name = module.iam.lambda_role_name
}

module "monitoring_ops" {
  source = "./modules/monitoring_ops"

  # 공통
  aws_region  = var.aws_region
  name_prefix = var.project_name

  tags = {
    Project   = var.project_name
    ManagedBy = "Terraform"
    Purpose   = "ops-monitoring"
  }

  #############################################
  # 알림 경로: CloudWatch Alarm -> SNS -> Lambda -> Slack
  #############################################
  create_sns_topic = true
  sns_topic_name   = "${var.project_name}-ops-alerts"

  # TODO: Slack 전송용 Lambda 준비 후 연결
  # 예시) module.lambda_alerts (별도 모듈)
  # slack_alert_lambda_arn  = module.lambda_alerts.arn
  # slack_alert_lambda_name = module.lambda_alerts.lambda_function_name

  # 임시로 이미 있는 Lambda를 넣으면 안 됨 (Slack 전송 로직이 없기 때문)
  # 아래 2개는 실제 Slack alert Lambda 만든 뒤 활성화해줘
  slack_alert_lambda_arn  = module.lambda_alert_slack.arn
  slack_alert_lambda_name = module.lambda_alert_slack.lambda_function_name

  #############################################
  # API Gateway (CloudWatch Metrics 차원)
  # 반드시 CloudWatch 콘솔에서 dimension 키 확인!
  #############################################
  api_gateway_namespace = "AWS/ApiGateway"
  api_gateway_dimensions = {
    ApiId = module.apigw.api_id
    Stage = "prod"
  }

  apigw_latency_p95_threshold_ms = 1000
  # API Gateway 알람 빠르게 (1분 단위)
  apigw_4xx_period_seconds     = 60
  apigw_4xx_evaluation_periods = 1

  apigw_5xx_period_seconds     = 60
  apigw_5xx_evaluation_periods = 1

  # (선택) Latency도 빠르게
  apigw_latency_period_seconds      = 60
  apigw_latency_evaluation_periods  = 1
  apigw_latency_datapoints_to_alarm = 1

  #############################################
  # Lambda (함수별)
  #############################################
  lambda_function_names = {
    shorten  = module.lambda_shorten.lambda_function_name
    redirect = module.lambda_redirect.lambda_function_name
    stats    = module.lambda_stats.lambda_function_name
    analyze  = module.lambda_analyze.lambda_function_name
  }

  # Errors 알람 대상 (우선)
  lambda_error_alarm_targets = [
    "shorten",
    "redirect",
    "stats"
  ]

  # Throttles 알람 대상 (우선)
  lambda_throttle_alarm_targets = [
    "shorten",
    "redirect"
  ]

  # Duration p95 임계치 (선택)
  lambda_duration_thresholds_ms = {
    redirect = 1000
    shorten  = 1500
    stats    = 1500
    # analyze는 배치성이라 초기에 제외해도 됨
    # analyze = 5000
  }


  #############################################
  # Dashboard
  #############################################
  create_dashboard = true
  dashboard_name   = "${var.project_name}-ops-monitoring"

  ###################################################
  # EventBridge 모니터링 대시보드 
  #############################################
  eventbridge_monitoring_dashboard_enabled = true
  eventbridge_monitoring_dashboard_name    = "url-shortener-ops-eventbridge-monitoring"

  # 실제 네 EventBridge rule 리소스/모듈 output 이름으로 바꿔 넣기
  eventbridge_monitoring_rule_names = [
    aws_cloudwatch_event_rule.analyze_agg_24h_30m.name,
    aws_cloudwatch_event_rule.analyze_agg_5m.name,
    aws_cloudwatch_event_rule.analyze_ai_30m.name,
  ]

  # 최근 1시간 기준 합계(예: 12/2/1) 보기 좋게
  eventbridge_monitoring_period_seconds = 300

  enable_ai_summary_subscription = true
  ai_summary_lambda_arn          = module.lambda_alert_slack_ai.arn
  ai_summary_lambda_name         = module.lambda_alert_slack_ai.lambda_function_name

}


#alert_slack
module "lambda_alert_slack" {
  source = "./modules/lambda"

  project_name  = var.project_name
  function_name = "${var.project_name}-ops-alert-slack" # => url-shortener-ops-alert-slack
  role_arn      = module.iam.lambda_role_arn

  source_dir = "${path.module}/../lambda/alert_slack"
  handler    = "handler.lambda_handler"
  runtime    = "python3.11"

  timeout     = 10
  memory_size = 128

  environment = {
    SLACK_WEBHOOK_URL = var.slack_webhook_url
  }
}

module "monitoring_canary" {
  source = "./modules/monitoring_canary"

  enabled        = true
  name_prefix    = "url-shortener"
  canary_name    = "url-shortener-e2e-canary"
  dashboard_name = "url-shortener-ops-canary-monitoring"

  api_base_url = "https://api.shortify.cloud"

  # 5분마다 실행 (3회 연속 실패면 약 15분 연속 실패 시 ALARM)
  canary_schedule_expression = "rate(5 minutes)"
  alarm_period_seconds       = 300

  #  Terraform으로 canary 전용 버킷 생성
  create_artifact_bucket  = true
  artifact_s3_bucket_name = "shortify-cloud-canary-jh"
  artifact_s3_prefix      = "synthetics/url-shortener"

  test_shorten_url   = "https://example.com/canary"
  test_shorten_title = "synthetics-canary-test"
  ai_period          = "P#30MIN"

  # 대시보드에서만 볼거면 비워둬도 됨
  alarm_actions = []
  ok_actions    = []

  tags = {
    Project = "url-shortener"
    Managed = "terraform"
  }
}

module "lambda_alert_slack_ai" {
  source = "./modules/lambda"

  project_name  = var.project_name
  function_name = "${var.project_name}-ops-alert-slack-ai-summary"
  role_arn      = module.iam.lambda_role_arn

  source_dir = "${path.module}/../lambda/alert_slack_ai"
  handler    = "handler.lambda_handler"
  runtime    = "python3.11"

  timeout     = 15
  memory_size = 256

  environment = {
    SLACK_WEBHOOK_URL = var.slack_webhook_url_ai_summary

    # Bedrock (Claude Sonnet)
    BEDROCK_REGION    = var.aws_region
    BEDROCK_MODEL_ID  = "apac.amazon.nova-lite-v1:0"

    # AI 요약 정책
    AI_ON_STATES    = "ALARM"
    SEND_OK_SIMPLE  = "true"
  }
}