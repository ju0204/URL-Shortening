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
