data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.project_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project = var.project_name
  }
}

# DynamoDB least-privilege policy
data "aws_iam_policy_document" "dynamodb_access" {
  # urls: Put/Get/Update (clickCount 증가, title/expiresAt 업데이트 등)
  statement {
    sid    = "UrlsTableAccess"
    effect = "Allow"
    actions = concat(
      ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Scan"],
      var.enable_delete_item ? ["dynamodb:DeleteItem"] : []
    )
    resources = [var.urls_table_arn]
  }

  # clicks: Put/Query (GetItem 제외)
  statement {
    sid    = "ClicksTableAccess"
    effect = "Allow"
    actions = concat(
      ["dynamodb:PutItem", "dynamodb:Query"],
      var.enable_delete_item ? ["dynamodb:DeleteItem"] : []
    )
    resources = [var.clicks_table_arn]
  }

  # insights: Put/Get/Update/Query/Scan
  statement {
    sid    = "InsightsTableAccess"
    effect = "Allow"
    actions = concat(
      ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"],
      var.enable_delete_item ? ["dynamodb:DeleteItem"] : []
    )
    resources = [var.insights_table_arn]
  }

  # ai: Put (AI 결과 누적 저장)
  statement {
    sid    = "AiTableAccess"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:GetItem"
    ]
    resources = [var.ai_table_arn]
  }


}

resource "aws_iam_policy" "dynamodb_access" {
  name   = "${var.project_name}-dynamodb-access"
  policy = data.aws_iam_policy_document.dynamodb_access.json
}

resource "aws_iam_role_policy_attachment" "attach_dynamodb_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.dynamodb_access.arn
}

# Lambda 로그(CloudWatch Logs) 권한: 운영/디버깅 필수
resource "aws_iam_role_policy_attachment" "attach_lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Bedrock 정책 추가 
# =========================
# Bedrock Invoke 권한 (Nova 2개 호출용)
# =========================
data "aws_iam_policy_document" "bedrock_invoke" {
  count = var.enable_bedrock ? 1 : 0

  statement {
    sid    = "BedrockInvokeModel"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]
    resources = var.bedrock_model_arns
  }
}

resource "aws_iam_policy" "bedrock_invoke" {
  count  = var.enable_bedrock ? 1 : 0
  name   = "${var.project_name}-bedrock-invoke"
  policy = data.aws_iam_policy_document.bedrock_invoke[0].json
}

resource "aws_iam_role_policy_attachment" "attach_bedrock_invoke" {
  count      = var.enable_bedrock ? 1 : 0
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.bedrock_invoke[0].arn
}

# =========================
# CloudWatch Custom Metrics 권한 (PutMetricData)
# =========================
data "aws_iam_policy_document" "cloudwatch_metrics" {
  statement {
    sid    = "CloudWatchPutMetricData"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData"
    ]
    # PutMetricData는 리소스 레벨 제한이 거의 의미 없어서 보통 "*" 사용
    resources = ["*"]
  }
}

resource "aws_iam_policy" "cloudwatch_metrics" {
  name   = "${var.project_name}-cloudwatch-metrics"
  policy = data.aws_iam_policy_document.cloudwatch_metrics.json
}

resource "aws_iam_role_policy_attachment" "attach_cloudwatch_metrics" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.cloudwatch_metrics.arn
}

# =========================
# Bedrock 정책 추가 (AI Slack Summary 전용 - Claude Sonnet)
# 기존 bedrock_invoke 정책은 건드리지 않고 추가로 부여
# =========================
data "aws_iam_policy_document" "bedrock_invoke_ai_summary" {
  count = var.enable_ai_summary_bedrock ? 1 : 0

  statement {
    sid    = "BedrockInvokeModelForAISummary"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]

    # 안정성/빠른 적용 우선: 기존 정책은 그대로 두고, 새 정책만 넉넉하게 허용
    # 추후 안정화 후 Claude Sonnet 모델 ARN으로 좁혀도 됨.
    resources = ["*"]
  }
}

resource "aws_iam_policy" "bedrock_invoke_ai_summary" {
  count  = var.enable_ai_summary_bedrock ? 1 : 0
  name   = "${var.project_name}-bedrock-invoke-ai-summary"
  policy = data.aws_iam_policy_document.bedrock_invoke_ai_summary[0].json
}

resource "aws_iam_role_policy_attachment" "attach_bedrock_invoke_ai_summary" {
  count      = var.enable_ai_summary_bedrock ? 1 : 0
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.bedrock_invoke_ai_summary[0].arn
}