data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect = "Allow"
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
      ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"],
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

  # insights: Put/Get/Update/Query
  statement {
    sid    = "InsightsTableAccess"
    effect = "Allow"
    actions = concat(
      ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"],
      var.enable_delete_item ? ["dynamodb:DeleteItem"] : []
    )
    resources = [var.insights_table_arn]
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
