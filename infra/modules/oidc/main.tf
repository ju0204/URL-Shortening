resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # GitHub OIDC thumbprint (관례적으로 이 값 많이 사용)
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_owner}/${var.github_repo}:ref:refs/heads/${var.github_branch}"
      ]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.project_name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

data "aws_iam_policy_document" "deploy_policy" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [var.s3_bucket_arn]
  }

  statement {
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
    resources = ["${var.s3_bucket_arn}/*"]
  }

  statement {
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [var.cloudfront_dist_arn]
  }
}

resource "aws_iam_policy" "deploy" {
  name   = "${var.project_name}-github-deploy-policy"
  policy = data.aws_iam_policy_document.deploy_policy.json
}

resource "aws_iam_role_policy_attachment" "deploy" {
  role       = aws_iam_role.deploy.name
  policy_arn = aws_iam_policy.deploy.arn
}