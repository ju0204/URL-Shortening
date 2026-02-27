output "lambda_role_name" {
  value = aws_iam_role.lambda_exec.name
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda_exec.arn
}

output "dynamodb_policy_arn" {
  value = aws_iam_policy.dynamodb_access.arn
}
