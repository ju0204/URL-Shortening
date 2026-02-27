resource "aws_s3_bucket" "analytics" {
  bucket = var.analytics_bucket_name
}

resource "aws_s3_bucket_public_access_block" "analytics" {
  bucket                  = aws_s3_bucket.analytics.bucket
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "analytics" {
  bucket = aws_s3_bucket.analytics.bucket

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "analytics" {
  bucket = aws_s3_bucket.analytics.bucket
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "analytics" {
  bucket = aws_s3_bucket.analytics.bucket

  rule {
    id     = "expire-analytics"
    status = "Enabled"

    filter {}

    expiration {
      days = var.analytics_lifecycle_days
    }
  }
}

data "aws_iam_policy_document" "analyze_export_s3" {
  statement {
    sid       = "AllowListBucketAnalyticsPrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.analytics.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["analytics", "analytics/*"]
    }
  }

  statement {
    sid       = "AllowRWAnalyticsObjects"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.analytics.arn}/analytics/*"]
  }
}

resource "aws_iam_policy" "analyze_export_s3" {
  name   = "shortify-analyze-export-s3"
  policy = data.aws_iam_policy_document.analyze_export_s3.json
}

resource "aws_iam_role_policy_attachment" "attach_analyze_export_s3" {
  role       = var.analyze_lambda_role_name
  policy_arn = aws_iam_policy.analyze_export_s3.arn
}

########################################
# Athena / Glue Catalog (fact_clicks)
########################################

# (1) Athena 결과 저장 경로(쿼리 결과 파일)
resource "aws_s3_object" "athena_results_prefix" {
  bucket  = aws_s3_bucket.analytics.bucket
  key     = "${var.athena_results_prefix}/"
  content = ""
}

# (2) Athena Workgroup (선택이지만 강추)
resource "aws_athena_workgroup" "shortify" {
  name = "${var.project_name}-athena"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.analytics.bucket}/${var.athena_results_prefix}/"
    }
  }
}

# (3) Glue Database
resource "aws_glue_catalog_database" "shortify" {
  name = "${var.project_name}_analytics"
}

# (4) Glue Table: fact_clicks (JSON Lines)
resource "aws_glue_catalog_table" "fact_clicks" {
  name          = "fact_clicks"
  database_name = aws_glue_catalog_database.shortify.name
  table_type    = "EXTERNAL_TABLE"

  # 파티션 컬럼(dt/hr)은 S3 경로에서 가져오는 방식
  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "hr"
    type = "int"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics.bucket}/${var.analytics_prefix}/fact_clicks/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "json"
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    # ✅ JSON Lines 컬럼들(네 export 레코드 구조 기준)
    columns {
      name = "ts"
      type = "string"
    }
    columns {
      name = "shortId"
      type = "string"
    }
    columns {
      name = "referer"
      type = "string"
    }
    columns {
      name = "device"
      type = "string"
    }
    columns {
      name = "isSuspect"
      type = "boolean"
    }
    columns {
      name = "ipHash"
      type = "string"
    }
    columns {
      name = "userAgent"
      type = "string"
    }
  }

  # ✅ Partition Projection (MSCK REPAIR 없이 dt/hr 자동 인식)
  parameters = {
    "classification"     = "json"
    "projection.enabled" = "true"

    # dt=YYYY-MM-DD
    "projection.dt.type"   = "date"
    "projection.dt.format" = "yyyy-MM-dd"
    "projection.dt.range"  = "2026-01-01,NOW"

    # hr=00~23 (문자열로 폴더 만들었으니 string으로 다뤄도 OK)
    "projection.hr.type"   = "integer"
    "projection.hr.range"  = "0,23"
    "projection.hr.digits" = "2"

    # S3 경로 템플릿
    "storage.location.template" = "s3://${aws_s3_bucket.analytics.bucket}/${var.analytics_prefix}/fact_clicks/dt=$${dt}/hr=$${hr}/"
  }
}


#--- grafana iam role + policy 추가
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "grafana_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["grafana.amazonaws.com"]
    }

    # (선택이지만 추천) 같은 계정/워크스페이스에서만 assume 하게 제한
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
  # ✅ 로컬(네 계정의 IAM 주체)에서도 Assume 가능하게 추가
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_iam_role" "grafana_athena_role" {
  name               = "${var.project_name}-grafana-athena"
  assume_role_policy = data.aws_iam_policy_document.grafana_assume_role.json
}

data "aws_iam_policy_document" "grafana_athena_policy" {
  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:ListWorkGroups",
      "athena:GetWorkGroup",
      "athena:ListDataCatalogs",
      "athena:ListDatabases",
      "athena:ListTableMetadata",
      "athena:GetDataCatalog",
      "athena:GetDatabase"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GlueCatalogRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions"
    ]
    resources = ["*"]
  }

  # fact_clicks 원본 읽기 (ListBucket)
  statement {
    sid       = "S3ReadAnalytics"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.analytics.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.analytics_prefix}/*", var.analytics_prefix]
    }
  }

  statement {
    sid       = "S3GetAnalyticsObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.analytics.arn}/${var.analytics_prefix}/*"]
  }

  # Athena 결과 쓰기/읽기
  statement {
    sid       = "S3AthenaResultsRW"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.analytics.arn}/${var.athena_results_prefix}/*"]
  }

  # (추가) Athena 결과 prefix ListBucket  <<== 여기!
  statement {
    sid       = "S3ListAthenaResultsPrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.analytics.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.athena_results_prefix}/*", var.athena_results_prefix]
    }
  }

  statement {
    sid       = "S3GetBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.analytics.arn]
  }

  statement {
    sid       = "S3ListBucketForVerify"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.analytics.arn]
  }
}

resource "aws_iam_policy" "grafana_athena_policy" {
  name   = "${var.project_name}-grafana-athena"
  policy = data.aws_iam_policy_document.grafana_athena_policy.json
}

resource "aws_iam_role_policy_attachment" "attach_grafana_athena_policy" {
  role       = aws_iam_role.grafana_athena_role.name
  policy_arn = aws_iam_policy.grafana_athena_policy.arn
}

