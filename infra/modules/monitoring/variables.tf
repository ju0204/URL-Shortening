variable "region" { type = string }
variable "analytics_bucket_name" { type = string }

variable "analyze_lambda_role_arn" { type = string }
variable "analyze_lambda_role_name" { type = string } # attach용(arn 대신 name이 필요할 수 있음)

# (선택) lifecycle days
variable "analytics_lifecycle_days" {
  type    = number
  default = 90
}

variable "project_name" {
  type = string
}

variable "analytics_prefix" {
  type    = string
  default = "analytics"
}

variable "athena_results_prefix" {
  type    = string
  default = "analytics/athena-results"
}