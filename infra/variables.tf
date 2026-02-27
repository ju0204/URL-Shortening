variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "project_name" {
  type    = string
  default = "url-shortener"
}

variable "base_url" {
  type        = string
  description = "Short URL base, e.g. https://short.example.com"
  default     = ""
}

variable "slack_webhook_url" {
  description = "Slack Incoming Webhook URL for ops alerts"
  type        = string
  sensitive   = true
}

variable "slack_webhook_url_ai_summary" {
  description = "Slack Incoming Webhook URL for AI summary alert channel"
  type        = string
  sensitive   = true
}