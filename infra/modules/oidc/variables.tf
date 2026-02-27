variable "project_name" {
  type = string
}

variable "github_owner" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "github_branch" {
  type    = string
  default = "main"
}

variable "s3_bucket_arn" {
  type = string
}

variable "cloudfront_dist_arn" {
  type = string
}