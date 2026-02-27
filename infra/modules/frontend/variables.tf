variable "project_name" {
  type = string
}

variable "domain_name" {
  type = string
}

variable "hosted_zone_id" {
  type = string
}

variable "acm_cert_arn" {
  type = string
}

variable "enable_www" {
  type    = bool
  default = false
}

variable "www_domain_name" {
  type    = string
  default = ""
}

variable "bucket_name" {
  type = string
}