resource "aws_dynamodb_table" "urls" {
  name         = "${var.project_name}-urls"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "shortId"

  attribute {
    name = "shortId"
    type = "S"
  }

  # TTL: expiresAt (Number)
  ttl {
    attribute_name = var.urls_ttl_attribute
    enabled        = true
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project = var.project_name
    Name    = "${var.project_name}-urls"
  }
}

resource "aws_dynamodb_table" "clicks" {
  name         = "${var.project_name}-clicks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "shortId"
  range_key    = "timestamp"

  attribute {
    name = "shortId"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project = var.project_name
    Name    = "${var.project_name}-clicks"
  }
}

resource "aws_dynamodb_table" "insights" {
  name         = "${var.project_name}-insights"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "shortId"
  range_key    = "periodKey"

  attribute {
    name = "shortId"
    type = "S"
  }

  attribute {
    name = "periodKey"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project = var.project_name
    Name    = "${var.project_name}-insights"
  }
}

#ai 테이블 추가 
resource "aws_dynamodb_table" "ai" {
  name         = "${var.project_name}-ai"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "periodKey"
  range_key    = "aiGeneratedAt"

  attribute {
    name = "periodKey"
    type = "S"
  }

  attribute {
    name = "aiGeneratedAt"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project = var.project_name
    Name    = "${var.project_name}-ai"
  }
}
