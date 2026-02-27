variable "enabled" {
  description = "Enable monitoring canary resources"
  type        = bool
  default     = true
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "url-shortener"
}

variable "canary_name" {
  description = "CloudWatch Synthetics Canary name"
  type        = string
  default     = "url-shortener-e2e-canary"
}

variable "dashboard_name" {
  description = "CloudWatch dashboard name for canary monitoring"
  type        = string
  default     = "url-shortener-ops-canary-monitoring"
}

variable "api_base_url" {
  description = "Base URL of the API Gateway custom domain (e.g. https://api.shortify.cloud)"
  type        = string
}

variable "canary_schedule_expression" {
  description = "Canary schedule expression"
  type        = string
  default     = "rate(5 minutes)"
}

variable "canary_runtime_version" {
  description = "Synthetics runtime version"
  type        = string
  default     = "syn-nodejs-puppeteer-11.0"
}

variable "canary_timeout_in_seconds" {
  description = "Canary timeout seconds"
  type        = number
  default     = 60
}

variable "canary_memory_in_mb" {
  description = "Canary Lambda memory"
  type        = number
  default     = 960
}

variable "create_artifact_bucket" {
  description = "Whether to create a dedicated S3 bucket for canary artifacts"
  type        = bool
  default     = true
}

variable "artifact_s3_bucket_name" {
  description = "Name of S3 bucket to create for canary artifacts (used when create_artifact_bucket=true)"
  type        = string
  default     = "shortify-cloud-canary-jh"
}

variable "artifact_s3_bucket" {
  description = "Existing S3 bucket for canary artifacts (used when create_artifact_bucket=false)"
  type        = string
  default     = null

  validation {
    condition     = var.create_artifact_bucket || (var.artifact_s3_bucket != null && trim(var.artifact_s3_bucket, "") != "")
    error_message = "artifact_s3_bucket must be provided when create_artifact_bucket is false."
  }
}

variable "artifact_s3_prefix" {
  description = "S3 prefix for canary artifacts"
  type        = string
  default     = "synthetics/canary"
}

variable "test_shorten_url" {
  description = "Test target URL used in POST /shorten"
  type        = string
  default     = "https://example.com/canary"
}

variable "test_shorten_title" {
  description = "Optional test title used in POST /shorten"
  type        = string
  default     = "synthetics-canary-test"
}

variable "ai_period" {
  description = "Period query for /ai/latest"
  type        = string
  default     = "P#30MIN"
}

variable "alarm_evaluation_periods" {
  description = "Number of periods to evaluate for alarm"
  type        = number
  default     = 3
}

variable "alarm_datapoints_to_alarm" {
  description = "Datapoints to alarm (consecutive failures)"
  type        = number
  default     = 3
}

variable "alarm_period_seconds" {
  description = "Alarm period in seconds; should match canary schedule cadence"
  type        = number
  default     = 300
}

variable "alarm_actions" {
  description = "Optional alarm action ARNs (SNS etc). Leave empty to monitor only on dashboard."
  type        = list(string)
  default     = []
}

variable "ok_actions" {
  description = "Optional OK action ARNs"
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}