variable "project_name" {
  type = string
}

variable "urls_table_arn" {
  type = string
}

variable "clicks_table_arn" {
  type = string
}

variable "insights_table_arn" {
  type = string
}

# 필요할 때만 true로 켜서 DeleteItem 권한 포함
variable "enable_delete_item" {
  type    = bool
  default = false
}

#bedrock 관련 권한 추가
variable "enable_bedrock" {
  type    = bool
  default = true
}

variable "bedrock_model_arns" {
  type        = list(string)
  default     = ["*"]
  description = "Allowed Bedrock model ARNs for InvokeModel. Use ['*'] for simplest."
}

variable "ai_table_arn" {
  type = string
}

variable "enable_ai_summary_bedrock" {
  description = "Attach additional Bedrock invoke policy for AI Slack summary Lambda (Claude Sonnet)"
  type        = bool
  default     = false
}