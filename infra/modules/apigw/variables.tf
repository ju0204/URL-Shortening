variable "project_name" {
  type = string
}

variable "api_name" {
  type = string
}

variable "stage_name" {
  type    = string
  default = "prod"
}

#sorten lambda용
# Lambda integration에 필요 (lambda의 invoke_arn)
variable "lambda_invoke_arn" {
  type = string
}

# Lambda permission에 필요 (lambda function name)
variable "lambda_function_name" {
  type = string
}


# redirect lambda용
variable "redirect_lambda_invoke_arn" {
  type = string
}
variable "redirect_lambda_function_name" {
  type = string
}

#커스텀 도메인 설정 
variable "custom_domain_name" {
  type        = string
  description = "Custom domain for HTTP API (e.g. shortify.cloud). Empty to disable."
  default     = ""
}

variable "hosted_zone_id" {
  type        = string
  description = "Route53 hosted zone id for the domain."
  default     = ""
}

variable "acm_certificate_domain" {
  type        = string
  description = "Domain name to lookup ACM certificate (must be ISSUED in same region)."
  default     = ""
}

#stats lambda용
variable "stats_lambda_invoke_arn" {
  type    = string
  default = ""
}

variable "stats_lambda_function_name" {
  type    = string
  default = ""
}

# /ai/latest 호출
variable "analyze_lambda_invoke_arn" {
  type = string
}

variable "analyze_lambda_function_name" {
  type = string
}

